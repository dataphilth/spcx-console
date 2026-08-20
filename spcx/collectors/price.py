"""Daily price from stooq — free, no key, no terms problem for a public repo."""

from __future__ import annotations

import csv
import io
from datetime import date

from . import collector
from ..http import get
from ..models import Reading, Snapshot

URL = "https://stooq.com/q/d/l/?s={sym}.us&i=d"


@collector("price")
def collect(config: dict, snap: Snapshot) -> None:
    sym = config["criteria"]["ticker"].lower()
    url = URL.format(sym=sym)
    try:
        rows = list(csv.DictReader(io.StringIO(get(url).decode())))
    except Exception as exc:
        snap.fail("price", "price", str(exc))
        return
    if not rows or "Close" not in rows[-1]:
        snap.fail("price", "price", "stooq returned no usable rows (symbol may be wrong)")
        return
    last = rows[-1]
    snap.add(Reading(
        metric="price", value=float(last["Close"]), unit="USD",
        as_of=last["Date"], source="stooq daily close", source_url=url,
        collector="price", confidence="high",
    ))
    # 20-day realised range, for context only. Never a criterion.
    closes = [float(r["Close"]) for r in rows[-21:] if r.get("Close")]
    if len(closes) == 21:
        rng = (max(closes) - min(closes)) / closes[-1] * 100
        snap.add(Reading(
            metric="price_range_20d", value=round(rng, 1), unit="% of price",
            as_of=last["Date"], source="derived from stooq closes", source_url=url,
            collector="price", confidence="high",
            note="Context only. Volatility is explicitly not a criterion.",
        ))
