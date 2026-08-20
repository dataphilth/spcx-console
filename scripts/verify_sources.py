#!/usr/bin/env python3
"""Verify every data source before trusting a run.

Run this first, and any time a collector starts returning gaps:

    python scripts/verify_sources.py

It probes each endpoint, reports the actual response shape, and — for the SEC —
discovers which XBRL tags this filer really uses rather than assuming the ones
guessed in config/metrics.yaml. Guessing tags is the single most likely reason
a first run comes back empty, because tag choice varies by filer and by the
preparer's software.

Exits non-zero if anything a collector depends on is unreachable or misshapen.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spcx import store  # noqa: E402
from spcx.collectors import launches  # noqa: E402
from spcx.http import HttpStatusError, get  # noqa: E402

OK, WARN, BAD = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def report(source: str, status: str, detail: str) -> None:
    results.append((source, status, detail))
    mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}[status]
    print(f"[{mark}] {source:<22} {detail}")


# ----------------------------------------------------------------------------


def check_contact() -> bool:
    contact = os.environ.get("SPCX_CONTACT", "")
    if not contact or "@" not in contact:
        report("SPCX_CONTACT", BAD,
               "unset. The SEC requires a declaring contact and will block "
               "anonymous callers. export SPCX_CONTACT='you@example.com'")
        return False
    report("SPCX_CONTACT", OK, contact)
    return True


def check_sec_xbrl(config: dict) -> None:
    """Probe companyfacts and discover which tags actually carry quarterly data."""
    cik = config["criteria"]["cik"]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        facts = json.loads(get(url).decode())
    except HttpStatusError as exc:
        hint = " — check the CIK is zero-padded to 10 digits" if exc.status == 404 else ""
        report("SEC companyfacts", BAD, f"{exc}{hint}")
        return
    except Exception as exc:
        report("SEC companyfacts", BAD, str(exc))
        return

    gaap = facts.get("facts", {}).get("us-gaap", {})
    report("SEC companyfacts", OK,
           f"{facts.get('entityName', '?')} · {len(gaap)} us-gaap tags")

    # Which of the configured tags actually resolve?
    wanted = {m: s.get("tags", []) for m, s in config["metrics"]["metrics"].items()
              if s.get("collector") == "sec_xbrl"}
    missing: list[str] = []
    for metric, tags in wanted.items():
        hit = next((t for t in tags if t in gaap or t in facts.get("facts", {}).get("dei", {})), None)
        if hit:
            report(f"  tag {metric}", OK, hit)
        else:
            missing.append(metric)
            report(f"  tag {metric}", WARN, f"none of {tags} present")

    if missing:
        print("\n  Candidate tags this filer actually uses "
              "(paste the right ones into config/metrics.yaml):\n")
        for needle, label in [("Revenue", "revenue"), ("NetIncome", "net income"),
                              ("PaymentsToAcquire", "capex"),
                              ("NetCashProvided", "cash flow"),
                              ("CashAndCash", "cash"), ("SharesOutstanding", "shares")]:
            found = sorted(t for t in gaap if needle.lower() in t.lower())[:6]
            if found:
                print(f"    {label:<12} {', '.join(found)}")
        print()

    # Are quarterly durations actually present, or only annual?
    for tag in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"):
        node = gaap.get(tag)
        if not node:
            continue
        for entries in node.get("units", {}).values():
            quarterly = [e for e in entries if e.get("form") == "10-Q"]
            if quarterly:
                last = sorted(quarterly, key=lambda e: e.get("end", ""))[-1]
                report("  10-Q periods", OK,
                       f"{tag}: latest {last.get('end')} ({last.get('fy')}{last.get('fp')})")
            else:
                report("  10-Q periods", WARN,
                       f"{tag}: no 10-Q facts — the filer may only have annual data yet")
            break
        break

    # Segment data is expected to be absent. Confirm it, so the manual half is
    # a documented necessity rather than an untested assumption.
    seg = [t for t in gaap if "Segment" in t]
    report("  segment tags", WARN if not seg else OK,
           "absent as expected — companyfacts drops dimensional facts, so segment "
           "figures stay manual" if not seg else f"{len(seg)} present, worth a look")


def check_sec_submissions(config: dict) -> None:
    cik = config["criteria"]["cik"]
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = json.loads(get(url).decode())
    except Exception as exc:
        report("SEC submissions", BAD, str(exc))
        return
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    if not forms:
        report("SEC submissions", BAD, "no recent filings array")
        return
    report("SEC submissions", OK,
           f"{len(forms)} recent · latest {forms[0]} on {recent['filingDate'][0]}")


def check_price(config: dict) -> None:
    sym = config["criteria"]["ticker"].lower()
    url = f"https://stooq.com/q/d/l/?s={sym}.us&i=d"
    try:
        body = get(url).decode()
    except Exception as exc:
        report("stooq price", BAD, str(exc))
        return
    lines = body.strip().splitlines()
    if len(lines) < 2 or "Close" not in lines[0]:
        report("stooq price", BAD,
               f"no usable CSV (got {body[:60]!r}). stooq returns a bare error string "
               f"for unknown symbols — confirm '{sym}.us' exists, or swap the collector "
               f"for another free source.")
        return
    report("stooq price", OK, f"{len(lines)-1} rows · latest {lines[-1]}")


def check_launches() -> None:
    # Probe exactly what the collector will call. These were previously separate
    # defaults -- the verifier checked lldev while collect() read production --
    # so a green verification said nothing about the run that followed it.
    base = launches.BASE
    which = ("production" if base == launches.PROD
             else "lldev development mirror" if base == launches.DEV
             else "custom")
    report("LL2 base", OK if base == launches.PROD else WARN,
           f"{which} - {base}"
           + ("" if base == launches.PROD
              else " (data may lag; unset SPCX_LL2_BASE for a production check)"))

    year = date.today().year
    probes = {
        "falcon YTD": (f"{base}?lsp__id=121&net__gte={year}-01-01T00:00:00Z"
                       f"&search=Falcon&mode=list&limit=1&status__ids=3"),
        "starship (suborbital included)": (f"{base}?lsp__id=121&search=Starship&mode=list"
                                           f"&limit=1&status__ids=3,4&include_suborbital=true"),
        "starship (default filter)": (f"{base}?lsp__id=121&search=Starship&mode=list"
                                      f"&limit=1&status__ids=3,4"),
        # Control probe. Without it, "included == default" is ambiguous: it can
        # mean the default already covers suborbital, or that LL2 is ignoring
        # the parameter altogether. Those call for opposite responses, so the
        # difference has to be measured rather than assumed.
        "starship (suborbital excluded)": (f"{base}?lsp__id=121&search=Starship&mode=list"
                                           f"&limit=1&status__ids=3,4&include_suborbital=false"),
    }
    counts = {}
    for label, url in probes.items():
        try:
            data = json.loads(get(url, throttle=2.0).decode())
        except Exception as exc:
            report(f"LL2 {label}", BAD, str(exc))
            continue
        counts[label] = data.get("count")
        report(f"LL2 {label}", OK, f"count={data.get('count')}")

    a = counts.get("starship (suborbital included)")
    b = counts.get("starship (default filter)")
    c = counts.get("starship (suborbital excluded)")
    if a is None or b is None or c is None:
        return

    if a == c:
        report("  suborbital check", WARN,
               f"include_suborbital looks inert: =true and =false both return {a}. "
               f"L8 would count whatever the default happens to mean. Verify by hand.")
    elif a > 0 and c == 0:
        if b == a:
            report("  suborbital check", OK,
                   f"parameter is live (=false yields 0) and all {a} flights are "
                   f"suborbital. This LL2 version already includes them by default, so "
                   f"include_suborbital=true is belt-and-braces, not load-bearing.")
        else:
            report("  suborbital check", OK,
                   f"confirmed: the default filter hides {a - b} of {a} flights. "
                   f"include_suborbital is load-bearing.")
    else:
        report("  suborbital check", WARN,
               f"unexpected combination: true={a} default={b} false={c}. Verify L8 by hand.")


def check_constellation() -> None:
    for group in ("starlink", "kuiper"):
        url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json"
        try:
            objs = json.loads(get(url, throttle=1.0, retries=1).decode())
        except HttpStatusError as exc:
            if exc.status == 403 and "has not updated" in exc.body:
                report(f"CelesTrak {group}", OK,
                       "reachable; already downloaded since last 2h update (this is "
                       "the expected response, not an error)")
            else:
                report(f"CelesTrak {group}", BAD, str(exc))
            continue
        except Exception as exc:
            report(f"CelesTrak {group}", BAD, str(exc))
            continue
        if not isinstance(objs, list) or not objs:
            report(f"CelesTrak {group}", WARN,
                   f"group returned {type(objs).__name__} with no objects — the group "
                   f"name may have changed (Amazon rebranded Kuiper to Leo)")
            continue
        report(f"CelesTrak {group}", OK,
               f"{len(objs)} objects · e.g. {objs[0].get('OBJECT_NAME')}")


# ----------------------------------------------------------------------------


def main() -> int:
    print("Verifying data sources. Nothing is written; this is read-only.\n")
    config = store.load_config()

    have_contact = check_contact()
    print()
    if have_contact:
        check_sec_xbrl(config)
        print()
        check_sec_submissions(config)
    else:
        report("SEC", BAD, "skipped — no contact set")
    print()
    check_price(config)
    print()
    check_launches()
    print()
    check_constellation()

    failed = [r for r in results if r[1] == BAD]
    warned = [r for r in results if r[1] == WARN]
    print(f"\n{len(results) - len(failed) - len(warned)} passed, "
          f"{len(warned)} warnings, {len(failed)} failures")

    if failed:
        print("\nFailures block a useful run:")
        for source, _, detail in failed:
            print(f"  - {source}: {detail}")
        print("\nA collector that cannot reach its source records a gap rather than a "
              "value, so a run will still complete — it will just be mostly empty.")
    if warned:
        print("\nWarnings usually mean a config change is needed, not a broken source.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
