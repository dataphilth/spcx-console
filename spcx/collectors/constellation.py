"""Constellation sizes from Celestrak's public GP catalogue.

Counts tracked objects, which is not the same as working satellites — deorbiting
hardware stays in the catalogue for a while. Confidence is set to medium for that
reason and the note says so, because an unqualified count here would read as more
precise than it is.
"""

from __future__ import annotations

import json
from datetime import date

from . import collector
from ..http import HttpStatusError, get
from ..models import Reading, Snapshot

GP = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json"
GROUPS = {"starlink_satellites_tracked": "starlink", "amazon_leo_satellites": "kuiper"}


@collector("constellation")
def collect(config: dict, snap: Snapshot) -> None:
    today = date.today().isoformat()
    for metric, group in GROUPS.items():
        url = GP.format(group=group)
        try:
            objs = json.loads(get(url, throttle=1.0).decode())
        except HttpStatusError as exc:
            if exc.status == 403 and "has not updated" in exc.body:
                snap.fail(metric, "constellation",
                          "CelesTrak: no update since last download (expected; "
                          "GP data refreshes every 2h)")
            else:
                snap.fail(metric, "constellation", str(exc))
            continue
        except Exception as exc:
            snap.fail(metric, "constellation", str(exc))
            continue
        snap.add(Reading(
            metric=metric, value=len(objs), unit="tracked objects",
            as_of=today, source=f"Celestrak GP catalogue, group={group}",
            source_url=url, collector="constellation", confidence="medium",
            note="Tracked objects, not working satellites. Deorbiting hardware "
                 "remains catalogued for a period after end of life.",
        ))
