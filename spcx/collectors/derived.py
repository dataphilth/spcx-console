"""Metrics computed from other readings.

Derived values inherit the *worst* confidence and the *oldest* as-of date of
their inputs. A ratio built on a ninety-day-old denominator is a ninety-day-old
number, and saying otherwise would let staleness launder itself through
arithmetic.
"""

from __future__ import annotations

from datetime import date

from . import collector
from ..models import Reading, Snapshot

RANK = {"high": 2, "medium": 1, "low": 0}
UNRANK = {v: k for k, v in RANK.items()}


def _combine(snap: Snapshot, inputs: list[str]) -> tuple[str, str]:
    readings = [snap.get(m) for m in inputs]
    if any(r is None for r in readings):
        raise KeyError(f"missing inputs: {[m for m, r in zip(inputs, readings) if r is None]}")
    conf = UNRANK[min(RANK[r.confidence] for r in readings)]
    as_of = min(r.as_of for r in readings)
    return conf, as_of


def _emit(snap: Snapshot, metric: str, value, unit: str, inputs: list[str], note: str, period=None) -> None:
    try:
        conf, as_of = _combine(snap, inputs)
    except KeyError as exc:
        snap.fail(metric, "derived", str(exc))
        return
    snap.add(Reading(
        metric=metric, value=value, unit=unit, as_of=as_of, period=period,
        source=f"derived from {', '.join(inputs)}",
        source_url="spcx/collectors/derived.py", collector="derived",
        confidence=conf, note=note,
    ))


def _ttm(history: list, snap: Snapshot, metric: str, n: int = 4) -> float | None:
    """Sum the last `n` distinct fiscal periods, current snapshot included.

    Returns None rather than a partial sum: three quarters summed and labelled
    trailing-twelve-month is a wrong number, not an approximate one.
    """
    seen: dict[str, float] = {}
    for s in list(history) + [snap]:
        r = s.get(metric)
        if r is None or r.value is None or not r.period:
            continue
        try:
            seen[r.period] = float(r.value)
        except (TypeError, ValueError):
            continue
    periods = sorted(seen)[-n:]
    if len(periods) < n:
        return None
    return sum(seen[p] for p in periods)


@collector("derived")
def collect(config: dict, snap: Snapshot) -> None:
    today = date.today()
    history = config.get("history", [])

    rev_ttm_m = _ttm(history, snap, "revenue_quarterly")
    if rev_ttm_m is not None:
        _emit(snap, "revenue_ttm", round(rev_ttm_m / 1000, 2), "$B", ["revenue_quarterly"],
              "Sum of four reported quarters. Needs four on record; reports nothing "
              "until it has them.")

    ocf = _ttm(history, snap, "operating_cash_flow_quarterly")
    capex = _ttm(history, snap, "capex_quarterly")
    if ocf is not None and capex is not None:
        _emit(snap, "fcf_ttm", round((ocf - capex) / 1000, 2), "$B",
              ["operating_cash_flow_quarterly", "capex_quarterly"],
              "Operating cash flow less capex. Feeds S1, the load-bearing wall of "
              "the bear case.")

    ytd = snap.value("falcon_launches_ytd")
    if ytd is not None:
        doy = today.timetuple().tm_yday
        _emit(snap, "falcon_launches_annualized", round(ytd * 365 / doy), "launches/yr",
              ["falcon_launches_ytd"],
              "Straight-line annualisation. Launch cadence is not uniform across a "
              "year, so this is directional until Q4.", period=str(today.year))

    price = snap.value("price")
    shares = snap.value("shares_outstanding")
    if price is not None and shares is not None:
        mcap = price * shares / 1000  # shares in millions -> $B
        _emit(snap, "market_cap", round(mcap, 1), "$B", ["price", "shares_outstanding"],
              "Uses the most recent reported share count, which lags the actual "
              "count between filings.")
        rev_ttm = snap.value("revenue_ttm")
        if rev_ttm:
            _emit(snap, "price_to_sales_ttm", round(mcap / rev_ttm, 1), "x",
                  ["price", "shares_outstanding", "revenue_ttm"],
                  "Trailing, not forward. On a company growing revenue at triple "
                  "digits the trailing multiple overstates the forward one.")
