"""Catalyst calendar: what's inside the lookahead window, what just passed."""
from __future__ import annotations

import datetime as dt


def upcoming(catalysts: list[dict], today: dt.date, lookahead_days: int) -> list[dict]:
    out = []
    for c in catalysts:
        days = (c["date"] - today).days
        if 0 <= days <= lookahead_days:
            out.append({**c, "date": c["date"].isoformat(), "days": days})
    return out


def recent(catalysts: list[dict], today: dt.date, lookback_days: int = 7) -> list[dict]:
    out = []
    for c in catalysts:
        days = (today - c["date"]).days
        if 0 < days <= lookback_days:
            out.append({**c, "date": c["date"].isoformat(), "days_ago": days})
    return out


def horizon(catalysts: list[dict], today: dt.date, n: int = 8) -> list[dict]:
    out = []
    for c in catalysts:
        days = (c["date"] - today).days
        if days >= 0:
            out.append({**c, "date": c["date"].isoformat(), "days": days})
    return out[:n]
