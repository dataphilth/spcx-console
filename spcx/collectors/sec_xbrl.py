"""Financials from the SEC's XBRL companyfacts API.

Free, no key, requires a declaring User-Agent. One request returns every tagged
fact the company has filed, which is why this collector fetches once and
extracts many metrics rather than making a call per metric.

Known limitation, and it is the reason config/metrics.yaml has a manual half:
companyfacts drops dimensional facts. Segment-level revenue and operating income
are tagged with a segment axis, so they are not retrievable here. They come from
the manual pass instead.
"""

from __future__ import annotations

import json

from . import collector
from ..http import get
from ..models import Reading, Snapshot

FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
QUARTERLY_FORMS = {"10-Q", "10-K"}


def _period(fact: dict) -> str | None:
    fy, fp = fact.get("fy"), fact.get("fp")
    if not fy or not fp:
        return None
    return f"{fy}{fp}" if fp != "FY" else f"{fy}Q4"


def _pick(facts: dict, tags: list[str]) -> tuple[dict, str] | None:
    """Most recent quarterly fact for the first tag that has one."""
    for tag in tags:
        for taxonomy in ("us-gaap", "dei"):
            node = facts.get("facts", {}).get(taxonomy, {}).get(tag)
            if not node:
                continue
            for unit_key, entries in node.get("units", {}).items():
                quarterly = [
                    e for e in entries
                    if e.get("form") in QUARTERLY_FORMS and _period(e)
                    and (e.get("start") is None or _span_days(e) <= 100)
                ]
                if quarterly:
                    quarterly.sort(key=lambda e: (e.get("end", ""), e.get("filed", "")))
                    return quarterly[-1], tag
    return None


def _span_days(e: dict) -> int:
    from datetime import date as _d
    if not e.get("start") or not e.get("end"):
        return 0
    return (_d.fromisoformat(e["end"]) - _d.fromisoformat(e["start"])).days


@collector("sec_xbrl")
def collect(config: dict, snap: Snapshot) -> None:
    cik = config["criteria"]["cik"]
    url = FACTS.format(cik=cik)
    try:
        facts = json.loads(get(url).decode())
    except Exception as exc:
        snap.fail("*", "sec_xbrl", f"companyfacts unavailable: {exc}")
        return

    for metric, spec in config["metrics"]["metrics"].items():
        if spec.get("collector") != "sec_xbrl":
            continue
        hit = _pick(facts, spec.get("tags", []))
        if hit is None:
            snap.fail(metric, "sec_xbrl", f"no quarterly fact for tags {spec.get('tags')}")
            continue
        fact, tag = hit
        raw = fact["val"]
        scale = spec.get("scale", 0.000001 if spec["unit"] in ("$M",) else 1)
        if spec["unit"] == "$M":
            scale = 0.000001
        elif spec["unit"] == "$B":
            scale = 0.000000001
        elif spec["unit"] == "M":
            scale = 0.000001
        snap.add(Reading(
            metric=metric, value=round(raw * scale, 3), unit=spec["unit"],
            as_of=fact["end"], period=_period(fact),
            source=f"SEC XBRL {tag}, {fact.get('form')} filed {fact.get('filed')}",
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            collector="sec_xbrl", confidence="high",
            note=f"accession {fact.get('accn', '')}",
        ))
