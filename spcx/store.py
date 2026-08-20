"""Snapshot storage.

Append-only by construction: snapshots are named by run date and refused if one
already exists unless --force is passed. Git is the audit log; rewriting history
would defeat the point of keeping one.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import Snapshot

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"
CONFIG_DIR = ROOT / "config"


def load_config() -> dict:
    return {
        "criteria": yaml.safe_load((CONFIG_DIR / "criteria.yaml").read_text(encoding="utf-8")),
        "metrics": yaml.safe_load((CONFIG_DIR / "metrics.yaml").read_text(encoding="utf-8")),
        "manual": yaml.safe_load((CONFIG_DIR / "manual_state.yaml").read_text(encoding="utf-8")),
    }


def history(limit: int | None = None) -> list[Snapshot]:
    """All snapshots, oldest first."""
    files = sorted(SNAP_DIR.glob("*.json"))
    if limit:
        files = files[-limit:]
    return [Snapshot.from_dict(json.loads(f.read_text(encoding="utf-8"))) for f in files]


def write(snap: Snapshot, force: bool = False) -> Path:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / f"{snap.run_date}.json"
    if path.exists() and not force:
        raise FileExistsError(f"{path.name} already exists; pass --force to overwrite")
    path.write_text(json.dumps(snap.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_latest(payload: dict) -> Path:
    """The view layer's entry point. Overwritten every run by design."""
    out = ROOT / "data" / "latest.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
