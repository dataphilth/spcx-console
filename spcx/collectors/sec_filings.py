"""Recent filings from EDGAR submissions.

Watches for the things that change the picture between quarters: 8-K, S-1/424B,
and Form 4 insider transactions. Reported as a list; nothing here is a criterion
on its own, but a new 8-K is the usual reason a manual pass is due.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from . import collector
from ..http import get
from ..models import Reading, Snapshot

SUBS = "https://data.sec.gov/submissions/CIK{cik}.json"
WATCH = {"8-K", "10-Q", "10-K", "4", "424B4", "424B5", "S-1", "S-3", "SC 13G", "SC 13D"}


@collector("sec_filings")
def collect(config: dict, snap: Snapshot) -> None:
    cik = config["criteria"]["cik"]
    url = SUBS.format(cik=cik)
    try:
        data = json.loads(get(url).decode())
    except Exception as exc:
        snap.fail("filings_recent", "sec_filings", str(exc))
        return

    recent = data.get("filings", {}).get("recent", {})
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    out = []
    for form, filed, accn, doc in zip(
        recent.get("form", []), recent.get("filingDate", []),
        recent.get("accessionNumber", []), recent.get("primaryDocument", []),
    ):
        if filed < cutoff:
            break
        if form in WATCH:
            stripped = accn.replace("-", "")
            out.append({
                "form": form, "filed": filed,
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{stripped}/{doc}",
            })

    snap.add(Reading(
        metric="filings_recent", value=json.dumps(out), unit="list",
        as_of=date.today().isoformat(),
        source=f"EDGAR submissions, {len(out)} watched filings in 14 days",
        source_url=url, collector="sec_filings", confidence="high",
    ))
