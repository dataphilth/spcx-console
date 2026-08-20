"""Data models.

A Reading without provenance is a rumour, so provenance is not optional here:
every field that would let a future reader check the number is required at
construction time. Collectors that cannot supply one raise rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Any


CONFIDENCE = ("high", "medium", "low")


@dataclass(frozen=True)
class Reading:
    """One observation of one metric at one point in time."""

    metric: str
    value: float | int | str | None
    unit: str
    as_of: str                  # the date the underlying fact is true of
    source: str                 # human-readable description
    source_url: str             # where a reader can check it
    collector: str              # which module produced it
    confidence: str = "high"
    period: str | None = None   # e.g. "2026Q2"; None for point-in-time
    note: str = ""
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {CONFIDENCE}, got {self.confidence!r}")
        if not self.as_of:
            raise ValueError(f"{self.metric}: as_of is required")
        if self.value is not None and not self.source:
            raise ValueError(f"{self.metric}: a value requires a source")
        date.fromisoformat(self.as_of)  # raises on malformed dates

    @property
    def age_days(self) -> int:
        return (date.today() - date.fromisoformat(self.as_of)).days

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    """Every reading taken on one run. Written once, never edited."""

    run_date: str
    readings: dict[str, Reading] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def add(self, r: Reading) -> None:
        self.readings[r.metric] = r

    def fail(self, metric: str, collector: str, reason: str) -> None:
        """Record a collection failure. A gap is data; a fabricated value is not."""
        self.errors.append({"metric": metric, "collector": collector, "reason": reason})

    def get(self, metric: str) -> Reading | None:
        return self.readings.get(metric)

    def value(self, metric: str) -> float | None:
        r = self.readings.get(metric)
        if r is None or r.value is None:
            return None
        try:
            return float(r.value)
        except (TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "readings": {k: v.to_dict() for k, v in self.readings.items()},
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Snapshot":
        snap = cls(run_date=d["run_date"], errors=d.get("errors", []))
        for k, v in d.get("readings", {}).items():
            snap.readings[k] = Reading(**v)
        return snap


@dataclass
class Evaluation:
    """The result of testing one criterion against the record."""

    criterion_id: str
    case: str                   # long | short
    tier: int
    label: str
    status: str                 # clear | nearing | fired | unknown
    value: float | str | None
    threshold: float | str | None
    unit: str
    proximity: float | None     # 0..1, how far along toward firing
    streak: int                 # consecutive periods satisfying the rule
    required: int
    detail: str = ""
    stale_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
