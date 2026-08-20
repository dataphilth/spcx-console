"""Load the judgment half of the record from config/manual_state.yaml.

These readings are indistinguishable from automated ones downstream except in
their `collector` field and their as-of dates, which is the point: a stale manual
read ages visibly in the same ledger as everything else.
"""

from __future__ import annotations

from . import collector
from ..models import Reading, Snapshot


@collector("manual")
def collect(config: dict, snap: Snapshot) -> None:
    manual = config["manual"]
    specs = config["metrics"]["metrics"]
    for metric, entry in manual.get("metrics", {}).items():
        spec = specs.get(metric, {})
        snap.add(Reading(
            metric=metric, value=entry["value"], unit=spec.get("unit", ""),
            as_of=str(entry["as_of"]), period=str(entry.get("period") or "") or None,
            source=entry.get("source", "manual entry"),
            source_url=entry.get("source_url", "config/manual_state.yaml"),
            collector="manual", confidence=entry.get("confidence", "medium"),
        ))
