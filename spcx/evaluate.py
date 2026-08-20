"""Evaluate criteria against the snapshot record.

Design rules, in order of importance:

1. A criterion fires only when its stated condition is literally satisfied.
   "Close" is never "fired". Proximity is reported separately so that a nearly
   fired condition is visible without being promoted.

2. Consecutive counts run over distinct fiscal *periods*, not over daily
   snapshots. Quarterly metrics are deduplicated by period so that reading the
   same 10-Q ninety days in a row does not manufacture a ninety-quarter streak.
   This is the bug that quietly ruins this kind of system.

3. A missing value produces `unknown`, never `clear`. Absence of evidence is
   reported as absence, because the alternative reads as reassurance.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .models import Evaluation, Snapshot

OPS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
}

# How close to the threshold counts as "nearing", as a fraction of the
# declared display scale. Deliberately a single tunable constant rather than
# a per-criterion judgment call.
NEARING_BAND = 0.15

STALE_DAYS = {"daily": 5, "biweekly": 21, "quarterly": 100, "event": 400}


def _periods(history: list[Snapshot], metric: str) -> list[tuple[str, float]]:
    """Ordered (period, value) pairs, one per distinct period, most recent last.

    Later snapshots win for the same period — a restated figure supersedes the
    original rather than appending to the streak.
    """
    seen: dict[str, float] = {}
    order: list[str] = []
    for snap in history:
        r = snap.get(metric)
        if r is None or r.value is None:
            continue
        try:
            v = float(r.value)
        except (TypeError, ValueError):
            continue
        key = r.period or r.as_of
        if key not in seen:
            order.append(key)
        seen[key] = v
    return [(p, seen[p]) for p in order]


def _streak(pairs: list[tuple[str, float]], test) -> int:
    """Count consecutive most-recent periods satisfying `test`."""
    n = 0
    for _, v in reversed(pairs):
        if test(v):
            n += 1
        else:
            break
    return n


def _proximity(value: float, threshold: float, operator: str, scale: list | None) -> float | None:
    """0..1. 1.0 means the condition is satisfied on this reading."""
    if OPS[operator](value, threshold):
        return 1.0
    if not scale or len(scale) != 2:
        return None
    span = abs(scale[1] - scale[0])
    if span == 0:
        return None
    gap = abs(value - threshold) / span
    return max(0.0, min(1.0, 1.0 - gap))


def _status(satisfied_now: bool, streak: int, required: int, proximity: float | None) -> str:
    if streak >= required:
        return "fired"
    if satisfied_now or streak >= max(1, required - 1):
        return "nearing"
    if proximity is not None and proximity >= 1.0 - NEARING_BAND:
        return "nearing"
    return "clear"


def _eval_threshold(c: dict, history: list[Snapshot]) -> tuple[str, Any, float | None, int, str]:
    rule = c["rule"]
    pairs = _periods(history, rule["metric"])
    if not pairs:
        return "unknown", None, None, 0, "No reading on record."
    op, thr = rule["operator"], rule["threshold"]
    test = lambda v: OPS[op](v, thr)  # noqa: E731
    latest = pairs[-1][1]
    streak = _streak(pairs, test)
    prox = _proximity(latest, thr, op, c.get("scale"))
    required = rule.get("consecutive", 1)
    status = _status(test(latest), streak, required, prox)

    # Deadline-bounded criteria ("X fails to happen BY date D") cannot fire
    # before D. Until then the condition holding only means it is on track to
    # fire, which is `nearing`. Firing early would report a deadline as missed
    # while there is still time on the clock.
    deadline = rule.get("deadline")
    detail = f"{latest:g} {c.get('unit', '')} · fires {op} {thr:g}"
    if deadline:
        days = (date.fromisoformat(deadline) - date.today()).days
        detail += f" · by {deadline} ({days}d remaining)" if days >= 0 else f" · deadline {deadline} passed"
        if days >= 0 and status == "fired":
            status = "nearing"
        elif days < 0 and not test(latest):
            status = "clear"  # deadline passed without the condition being met
    if required > 1:
        detail += f" · {streak}/{required} periods"
    return status, latest, prox, streak, detail


def _eval_compare(c: dict, history: list[Snapshot]) -> tuple[str, Any, float | None, int, str]:
    rule = c["rule"]
    a_pairs = dict(_periods(history, rule["metric"]))
    b_pairs = _periods(history, rule["against"])
    if not b_pairs:
        return "unknown", None, None, 0, "No reading on record."
    op = rule["operator"]
    joined = [(p, a_pairs[p], v) for p, v in b_pairs if p in a_pairs]
    if not joined:
        return "unknown", None, None, 0, "Metrics never observed in the same period."
    streak = 0
    for _, a, b in reversed(joined):
        if OPS[op](a, b):
            streak += 1
        else:
            break
    required = rule.get("consecutive", 1)
    _, a_last, b_last = joined[-1]
    ratio = a_last / b_last if b_last else None
    status = _status(OPS[op](a_last, b_last), streak, required, None)
    detail = (f"{rule['metric']} {a_last:,.0f} vs {rule['against']} {b_last:,.0f}"
              f" ({ratio:.2f}x) · {streak}/{required} periods")
    return status, streak, (streak / required if required else None), streak, detail


def _eval_streak(c: dict, history: list[Snapshot]) -> tuple[str, Any, float | None, int, str]:
    rule = c["rule"]
    pairs = _periods(history, rule["metric"])
    if len(pairs) < 2:
        return "unknown", None, None, 0, "Needs at least two periods on record."
    direction = rule["direction"]
    deltas = [(pairs[i][1] - pairs[i - 1][1]) for i in range(1, len(pairs))]
    if direction == "down":
        test = lambda d: d < 0  # noqa: E731
    elif direction == "up":
        test = lambda d: d > 0  # noqa: E731
    else:  # up_or_flat
        test = lambda d: d >= 0  # noqa: E731
    streak = 0
    for d in reversed(deltas):
        if test(d):
            streak += 1
        else:
            break
    required = rule.get("periods", 2)
    status = _status(streak >= 1, streak, required, None)
    detail = (f"{pairs[-1][1]:g} {c.get('unit','')} · {direction} for {streak}/{required} "
              f"{rule.get('period_type','period')}s")
    return status, pairs[-1][1], (streak / required if required else None), streak, detail


def _eval_manual(c: dict, manual: dict) -> tuple[str, Any, float | None, int, str]:
    entry = manual.get("states", {}).get(c["rule"]["key"])
    if entry is None:
        return "unknown", None, None, 0, "No state recorded."
    state = entry.get("state", "unknown")
    if state not in ("clear", "nearing", "fired", "unknown"):
        state = "unknown"
    return state, state, None, 0, entry.get("detail", "")


def evaluate_one(c: dict, history: list[Snapshot], manual: dict) -> Evaluation:
    kind = c["rule"]["type"]
    if kind == "threshold":
        status, value, prox, streak, detail = _eval_threshold(c, history)
        required = c["rule"].get("consecutive", 1)
        threshold = c["rule"]["threshold"]
    elif kind == "compare":
        status, value, prox, streak, detail = _eval_compare(c, history)
        required = c["rule"].get("consecutive", 1)
        threshold = c["rule"]["against"]
    elif kind == "streak":
        status, value, prox, streak, detail = _eval_streak(c, history)
        required = c["rule"].get("periods", 2)
        threshold = c["rule"]["direction"]
    elif kind == "manual":
        status, value, prox, streak, detail = _eval_manual(c, manual)
        required, threshold = 1, None
    else:
        raise ValueError(f"{c['id']}: unknown rule type {kind!r}")

    stale = None
    metric = c["rule"].get("metric") or c["rule"].get("key")
    for snap in reversed(history):
        r = snap.get(metric) if metric else None
        if r is not None:
            stale = r.age_days
            break

    return Evaluation(
        criterion_id=c["id"], case=c["case"], tier=c["tier"], label=c["label"],
        status=status, value=value, threshold=threshold, unit=c.get("unit", ""),
        proximity=prox, streak=streak, required=required, detail=detail, stale_days=stale,
    )


def evaluate_all(criteria: dict, history: Iterable[Snapshot], manual: dict) -> list[Evaluation]:
    hist = list(history)
    return [evaluate_one(c, hist, manual) for c in criteria["criteria"]]


def summarise(evals: list[Evaluation]) -> dict[str, Any]:
    by = lambda s: [e.criterion_id for e in evals if e.status == s]  # noqa: E731
    nearing = [e for e in evals if e.status == "nearing" and e.proximity is not None]
    closest = max(nearing, key=lambda e: e.proximity, default=None)
    return {
        "fired": by("fired"),
        "nearing": by("nearing"),
        "unknown": by("unknown"),
        "clear": by("clear"),
        "closest_to_firing": closest.criterion_id if closest else None,
        "long_fired": [e.criterion_id for e in evals if e.status == "fired" and e.case == "long"],
        "short_fired": [e.criterion_id for e in evals if e.status == "fired" and e.case == "short"],
    }
