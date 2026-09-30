"""Relative volume: how heavy was the last session, and is there a scheduled reason for it?

Context only, like everything on the tape. Volume says how much changed hands, not
which way anyone leaned, so nothing here carries a long or short read.

Every comparison uses the sessions BEFORE the window being measured, so a big day
never inflates its own baseline. `calendar` lists anything scheduled that usually
brings volume (a tape catalyst, monthly options expiry, quarterly quad witching).
`needs_explaining` is true when the session was heavy and nothing on the calendar
accounts for it: that is the cue for the research layer to go find the news.
"""

from __future__ import annotations

import datetime as dt
from statistics import mean, pstdev

LABELS = ((0.7, "light"), (1.3, "ordinary"), (2.0, "heavy"), (3.0, "very heavy"))
QUAD_MONTHS = (3, 6, 9, 12)


def label(rvol: float | None) -> str | None:
    if rvol is None:
        return None
    for cut, name in LABELS:
        if rvol < cut:
            return name
    return "extreme"


def third_friday(year: int, month: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(4 - first.weekday()) % 7 + 14)


def calendar_for(session: dt.date, prev_session: dt.date | None, catalysts: list[dict]) -> list[dict]:
    """Scheduled items that land on this session, or on a non-trading day since the prior one."""
    lo = prev_session or session - dt.timedelta(days=1)
    out = []
    for c in catalysts:
        d = c["date"] if isinstance(c["date"], dt.date) else dt.date.fromisoformat(str(c["date"]))
        if lo < d <= session:
            out.append({"kind": c.get("kind", "catalyst"), "event": c["event"], "date": d.isoformat()})
    if session == third_friday(session.year, session.month):
        if session.month in QUAD_MONTHS:
            out.append({"kind": "expiry", "event": "Quarterly quad witching (options + futures expire; index rebalances)",
                        "date": session.isoformat()})
        else:
            out.append({"kind": "expiry", "event": "Monthly options expiration", "date": session.isoformat()})
    return out


def _avg(vols: list[float]) -> float | None:
    return mean(vols) if vols else None


def _ratio(num: float, den: float | None) -> float | None:
    return round(num / den, 2) if den else None


def profile(bars: list[dict], atr: float | None, catalysts: list[dict], params: dict | None = None) -> dict:
    params = params or {}
    base_n = int(params.get("rvol_baseline", 20))
    long_n = int(params.get("rvol_long_baseline", 60))
    trigger = float(params.get("rvol_needs_explaining", 1.3))
    bars = sorted(bars, key=lambda b: b["date"])
    n = len(bars)
    out: dict = {"sessions": n, "date": bars[-1]["date"] if bars else None}
    if n < 2:
        out["baseline_thin"] = True
        return out
    vols = [float(b["volume"]) for b in bars]
    last, prev = bars[-1], bars[-2]
    today_v = vols[-1]
    prior = vols[:-1]

    base = prior[-base_n:]
    avg20 = _avg(base)
    out.update(shares=int(today_v), avg20=int(avg20) if avg20 else None, rvol20=_ratio(today_v, avg20))
    sd = pstdev(base) if len(base) > 1 else 0
    out["z20"] = round((today_v - avg20) / sd, 2) if sd and avg20 else None
    if len(prior) >= long_n:
        avg60 = _avg(prior[-long_n:])
        out.update(avg60=int(avg60), rvol60=_ratio(today_v, avg60))
    else:
        out.update(avg60=None, rvol60=None)
    out["baseline_thin"] = len(prior) < long_n
    out["label"] = label(out["rvol20"])

    # Multi-session windows: last k sessions vs the base_n sessions before them.
    for k in (3, 5):
        if n > k + 1:
            win, before = vols[-k:], vols[:-k][-base_n:]
            b = _avg(before)
            out[f"shares_{k}d"] = int(sum(win))
            out[f"rvol_{k}d"] = _ratio(sum(win), b * k if b else None)
        else:
            out[f"shares_{k}d"] = out[f"rvol_{k}d"] = None

    # Where today ranks, and the last session that traded more.
    heavier = [b for b in bars[:-1] if float(b["volume"]) > today_v]
    out["heaviest_since"] = heavier[-1]["date"] if heavier else None
    out["heaviest_on_record"] = not heavier
    window = vols[-long_n:]
    out["rank_in_window"] = 1 + sum(1 for v in window[:-1] if v > today_v)
    out["rank_window"] = len(window)

    # Pair volume with the move so "heavy" is never read alone.
    pc = float(prev["close"])
    out["chg_1d_pct"] = round(100 * (float(last["close"]) / pc - 1), 2) if pc else None
    out["move_atr"] = round((float(last["close"]) - pc) / atr, 2) if atr else None

    session = dt.date.fromisoformat(last["date"])
    cal = calendar_for(session, dt.date.fromisoformat(prev["date"]), catalysts)
    out["calendar"] = cal
    out["needs_explaining"] = bool(out["rvol20"] is not None and out["rvol20"] >= trigger and not cal)
    return out
