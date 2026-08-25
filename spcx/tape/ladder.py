"""Accumulation ladder — a pre-commitment device, not a signal.

The bot's job is to say which band price is in, whether that band is funded,
whether the rules allow a fill, and whether the criteria board has paused the
ladder. It never says buy.

Pause rule, from the long-case criteria in config/criteria.yaml:
  any long Tier-1 FIRED           → STOP ADDING, reassess from scratch
  two or more long Tier-2 FIRED   → downgrade conviction, pause
"""

from __future__ import annotations


def gate_from_evaluations(evaluations: list[dict]) -> dict:
    longs = [e for e in evaluations if e.get("case") == "long"]
    t1 = [e["criterion_id"] for e in longs if e["tier"] == 1 and e["status"] == "fired"]
    t2 = [e["criterion_id"] for e in longs if e["tier"] == 2 and e["status"] == "fired"]
    nearing = [e["criterion_id"] for e in longs if e["status"] == "nearing"]
    out = {"tier1_fired": t1, "tier2_fired": t2, "long_nearing": nearing, "paused": False, "pause_reason": None}
    if t1:
        out["paused"] = True
        out["pause_reason"] = f"Long Tier-1 fired ({', '.join(t1)}) — STOP ADDING, reassess from scratch."
    elif len(t2) >= 2:
        out["paused"] = True
        out["pause_reason"] = f"{len(t2)} long Tier-2 fired ({', '.join(t2)}) — downgrade conviction, pause the ladder."
    return out


def evaluate(close: float, bands: list[dict], fills: list[dict], gate: dict, rules: list[str], budget: float) -> dict:
    in_band = next((b for b in bands if b["low"] <= close < b["high"]), None)
    by_band: dict[str, list[dict]] = {}
    for f in fills:
        by_band.setdefault(f.get("band", "?"), []).append(f)

    view = []
    for b in bands:
        prior = by_band.get(b["name"], [])
        lowest = min((f["price"] for f in prior), default=None)
        view.append({
            "name": b["name"], "low": b["low"], "high": b["high"],
            "planned_shares": b.get("shares", 0), "funded": bool(b.get("shares", 0)),
            "fills": len(prior), "lowest_fill": lowest, "active": in_band is b,
            "gated": bool(b.get("requires_criteria_check")),
            "blocked_by_repeat_rule": bool(prior) and lowest is not None and close >= lowest,
            "note": b.get("note"),
        })

    out = {
        "close": close, "active_band": in_band["name"] if in_band else None,
        "active_band_funded": bool(in_band and in_band.get("shares", 0)),
        "requires_criteria_check": bool(in_band and in_band.get("requires_criteria_check")),
        "paused": gate["paused"], "pause_reason": gate["pause_reason"],
        "budget_dollars": budget, "budget_set": budget > 0, "bands": view, "rules": rules,
    }
    if in_band is None:
        out["message"] = f"Close {close} is outside every defined band (above {bands[0]['high']} or below {bands[-1]['low']})."
    elif gate["paused"]:
        out["message"] = f"In band '{in_band['name']}' but the ladder is PAUSED: {gate['pause_reason']}"
    elif not out["active_band_funded"]:
        out["message"] = f"In band '{in_band['name']}' — defined but UNFUNDED (shares: 0 in config/tape.yaml). No plan to execute."
    else:
        bv = next(v for v in view if v["active"])
        if bv["blocked_by_repeat_rule"]:
            out["message"] = f"In band '{in_band['name']}' — already filled at {bv['lowest_fill']}; the repeat rule blocks another fill until a new low inside the band."
        else:
            gate_txt = " Written long Tier-1 criteria check required before any purchase." if out["requires_criteria_check"] else ""
            out["message"] = f"In band '{in_band['name']}' — plan calls for {in_band['shares']} shares.{gate_txt}"
    return out
