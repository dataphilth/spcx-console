"""Launch cadence from the Launch Library 2 API (thespacedevs).

Free tier is rate-limited to roughly 15 calls/hour, which is why this runs once
daily and pages rather than querying per-vehicle. Falcon cadence feeds L10;
Starship flight count feeds L8.
"""

from __future__ import annotations

import json
import os
from datetime import date

from . import collector
from ..http import get
from ..models import Reading, Snapshot

# lldev is the development mirror: same schema, far higher rate limit, data may
# lag slightly. Use it for verification runs so a debugging session cannot burn
# the production quota (15 calls/hour on the free tier).
PROD = "https://ll.thespacedevs.com/2.3.0/launches/"
DEV = "https://lldev.thespacedevs.com/2.3.0/launches/"
BASE = os.environ.get("SPCX_LL2_BASE", PROD)
SPACEX_ID = 121  # launch service provider id


def _count(url: str) -> tuple[int, str]:
    data = json.loads(get(url, throttle=2.0).decode())
    return int(data.get("count", 0)), url


@collector("launches")
def collect(config: dict, snap: Snapshot) -> None:
    today = date.today()
    year_start = f"{today.year}-01-01T00:00:00Z"
    now = today.isoformat() + "T23:59:59Z"

    falcon_url = (f"{BASE}?lsp__id={SPACEX_ID}&net__gte={year_start}&net__lte={now}"
                  f"&search=Falcon&mode=list&limit=1&status__ids=3")
    try:
        n, url = _count(falcon_url)
        snap.add(Reading(
            metric="falcon_launches_ytd", value=n, unit="launches",
            as_of=today.isoformat(), period=str(today.year),
            source="Launch Library 2, successful Falcon launches year to date",
            source_url=url, collector="launches", confidence="medium",
            note="Counts status=success only. Cross-check against the SpaceX manifest quarterly.",
        ))
    except Exception as exc:
        snap.fail("falcon_launches_ytd", "launches", str(exc))

    # include_suborbital is required here and its absence is a silent zero:
    # every Starship flight to date has flown a suborbital trajectory, so the
    # default (orbital only) filter excludes the entire programme.
    ship_url = (f"{BASE}?lsp__id={SPACEX_ID}&search=Starship&mode=list&limit=1"
                f"&status__ids=3,4&include_suborbital=true")
    try:
        n, url = _count(ship_url)
        snap.add(Reading(
            metric="starship_flights_total", value=n, unit="flights",
            as_of=today.isoformat(), period="cumulative",
            source="Launch Library 2, all Starship flights flown",
            source_url=url, collector="launches", confidence="medium",
            note="Total flights only. Orbital insertions are a manual read — the API "
                 "does not distinguish an orbital insertion from a suborbital arc.",
        ))
    except Exception as exc:
        snap.fail("starship_flights_total", "launches", str(exc))
