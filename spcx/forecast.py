"""Forecast log and Brier scoring.

The reason this exists: a research system that only records what happened is
indistinguishable from hindsight. Recording a probability *before* resolution,
then scoring it, is the only mechanism that tells you whether the criteria are
carrying information or just narrating.

Brier score: mean squared error of probabilistic forecasts. 0 is perfect, 0.25
is what you get by always saying 50%, and anything above the base-rate score
means the forecasts are actively worse than knowing nothing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "forecasts.yaml"


def load() -> list[dict]:
    if not LOG.exists():
        return []
    return yaml.safe_load(LOG.read_text(encoding="utf-8")).get("forecasts", []) or []


def save(items: list[dict]) -> None:
    LOG.write_text(yaml.safe_dump({"forecasts": items}, sort_keys=False, width=100), encoding="utf-8")


def add(statement: str, probability: float, resolve_by: str,
        criterion: str | None = None, basis: str = "") -> dict:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    date.fromisoformat(resolve_by)
    items = load()
    entry = {
        "id": f"f{len(items) + 1:04d}",
        "made_on": date.today().isoformat(),
        "statement": statement,
        "criterion": criterion,
        "probability": probability,
        "resolve_by": resolve_by,
        "basis": basis,
        "outcome": None,
        "resolved_on": None,
    }
    items.append(entry)
    save(items)
    return entry


def resolve(fid: str, outcome: bool, note: str = "") -> dict:
    items = load()
    for e in items:
        if e["id"] == fid:
            e["outcome"] = bool(outcome)
            e["resolved_on"] = date.today().isoformat()
            if note:
                e["resolution_note"] = note
            save(items)
            return e
    raise KeyError(f"no forecast {fid}")


def score() -> dict[str, Any]:
    resolved = [e for e in load() if e.get("outcome") is not None]
    if not resolved:
        return {"n": 0, "brier": None, "base_rate": None, "beats_base_rate": None}
    n = len(resolved)
    brier = sum((e["probability"] - float(e["outcome"])) ** 2 for e in resolved) / n
    base = sum(float(e["outcome"]) for e in resolved) / n
    base_brier = sum((base - float(e["outcome"])) ** 2 for e in resolved) / n
    overconf = sum(e["probability"] - float(e["outcome"]) for e in resolved) / n
    return {
        "n": n,
        "brier": round(brier, 4),
        "base_rate": round(base, 3),
        "base_rate_brier": round(base_brier, 4),
        "beats_base_rate": brier < base_brier,
        "mean_bias": round(overconf, 3),
        "bias_reading": ("over-forecasting" if overconf > 0.05
                         else "under-forecasting" if overconf < -0.05 else "roughly calibrated"),
    }


def overdue() -> list[dict]:
    today = date.today().isoformat()
    return [e for e in load() if e.get("outcome") is None and e["resolve_by"] < today]
