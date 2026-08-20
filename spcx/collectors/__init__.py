"""Collectors.

Each collector is a function taking (config, snapshot) and adding Readings.
A collector that cannot source a number calls `snapshot.fail(...)` and moves on.
It never substitutes a prior value, an estimate, or a placeholder — a gap in the
record is recoverable, a fabricated number in an audit trail is not.
"""

from __future__ import annotations

from typing import Callable

from ..models import Snapshot

REGISTRY: dict[str, Callable] = {}


def collector(name: str):
    def wrap(fn: Callable) -> Callable:
        REGISTRY[name] = fn
        return fn
    return wrap


def run_all(config: dict, snapshot: Snapshot, only: list[str] | None = None) -> Snapshot:
    """Run collectors in dependency order. `derived` runs last by construction."""
    order = ["sec_xbrl", "sec_filings", "price", "launches", "constellation",
             "manual", "derived"]
    for name in order:
        if only and name not in only:
            continue
        fn = REGISTRY.get(name)
        if fn is None:
            continue
        try:
            fn(config, snapshot)
        except Exception as exc:  # a broken collector must not lose the whole run
            snapshot.fail(metric="*", collector=name, reason=f"{type(exc).__name__}: {exc}")
    return snapshot


from . import constellation, derived, launches, manual, price, sec_filings, sec_xbrl  # noqa: E402,F401
