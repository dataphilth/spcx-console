"""Implied-volatility snapshot from the listed chain (yfinance, optional).

iv30 / iv90 are ATM implied vols interpolated in total variance to constant
maturities; expected_move is the front-expiry ATM straddle. Yahoo's per-contract
IV on a thin, young, 90-vol name is noisy — treat everything here as ±5 points.
Each snapshot is appended to data/iv_history.csv so IV rank/percentile become
meaningful once ~60 sessions accumulate; until then they are labelled as such.
"""

from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path

IV_COLUMNS = ["date", "spot", "iv_front", "iv30", "iv90", "front_expiry", "front_dte",
              "expected_move_usd", "expected_move_pct", "put_call_oi", "n_expiries"]


def _f(x, default: float = 0.0) -> float:
    """float() that treats None / NaN / unparsable as `default`. Yahoo chains are full of NaN cells."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) else v


def _atm(chain, spot: float) -> tuple[float | None, float | None, int]:
    """(atm_iv, mid, total_oi) for one side of the chain (a pandas DataFrame)."""
    if chain is None or len(chain) == 0 or "strike" not in chain:
        return None, None, 0
    rows = [r for r in chain.to_dict("records") if not math.isnan(_f(r.get("strike"), float("nan")))]
    if not rows:
        return None, None, 0
    row = min(rows, key=lambda r: abs(_f(r["strike"]) - spot))
    iv = _f(row.get("impliedVolatility"), float("nan"))
    iv = iv if not math.isnan(iv) and 0.05 < iv < 5 else None
    bid, ask, last = (_f(row.get(k)) for k in ("bid", "ask", "lastPrice"))
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else (last if last > 0 else None)
    oi = int(sum(_f(r.get("openInterest")) for r in rows))
    return iv, mid, oi


def _interp(points: list[tuple[int, float]], target: int) -> float | None:
    if not points:
        return None
    if len(points) == 1 or target <= points[0][0]:
        return points[0][1]
    if target >= points[-1][0]:
        return points[-1][1]
    for (d0, v0), (d1, v1) in zip(points, points[1:]):
        if d0 <= target <= d1:
            tv0, tv1 = v0 * v0 * d0, v1 * v1 * d1
            tv = tv0 + (tv1 - tv0) * (target - d0) / (d1 - d0)
            return math.sqrt(max(tv, 0) / target)
    return None


def fetch_snapshot(ticker: str, spot: float, today: date, max_expiries: int = 8) -> dict:
    import yfinance as yf  # optional

    t = yf.Ticker(ticker)
    expiries = list(t.options or [])
    if not expiries:
        raise RuntimeError("no listed expiries")
    points, front, c_oi, p_oi = [], None, 0, 0
    for exp in expiries[:max_expiries]:
        dte = (date.fromisoformat(exp) - today).days
        if dte < 3:
            continue
        try:
            oc = t.option_chain(exp)
        except Exception:  # noqa: BLE001
            continue
        civ, cmid, coi = _atm(oc.calls, spot)
        piv, pmid, poi = _atm(oc.puts, spot)
        c_oi, p_oi = c_oi + coi, p_oi + poi
        ivs = [v for v in (civ, piv) if v is not None]
        if not ivs:
            continue
        atm = sum(ivs) / len(ivs)
        points.append((dte, atm))
        if front is None:
            front = {"expiry": exp, "dte": dte, "iv": atm, "straddle": (cmid + pmid) if cmid and pmid else None}
    points.sort()
    if not points:
        raise RuntimeError("no usable ATM IV points")
    iv30, iv90 = _interp(points, 30), _interp(points, 90)
    em = front["straddle"] if front else None
    return {
        "date": today.isoformat(), "spot": round(spot, 2),
        "iv_front": round(front["iv"] * 100, 1) if front else None,
        "iv30": round(iv30 * 100, 1) if iv30 else None,
        "iv90": round(iv90 * 100, 1) if iv90 else None,
        "front_expiry": front["expiry"] if front else None,
        "front_dte": front["dte"] if front else None,
        "expected_move_usd": round(em, 2) if em else None,
        "expected_move_pct": round(100 * em / spot, 1) if em else None,
        "put_call_oi": round(p_oi / c_oi, 2) if c_oi else None,
        "n_expiries": len(points),
    }


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return sorted(csv.DictReader(fh), key=lambda r: r["date"])


def append_history(snap: dict, path: Path) -> list[dict]:
    rows = [r for r in load_history(path) if r["date"] != snap["date"]]
    rows.append({k: ("" if snap.get(k) is None else snap.get(k)) for k in IV_COLUMNS})
    rows.sort(key=lambda r: r["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=IV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows


def rank(history: list[dict], current: float | None, min_rows: int) -> dict:
    out = {"iv_rank": None, "iv_percentile": None, "iv_history_days": len(history), "meaningful": False}
    vals = []
    for r in history:
        try:
            vals.append(float(r["iv30"]))
        except (TypeError, ValueError, KeyError):
            pass
    if current is None or not vals:
        return out
    lo, hi = min(vals), max(vals)
    out["iv_rank"] = round(100 * (current - lo) / (hi - lo), 1) if hi > lo else None
    out["iv_percentile"] = round(100 * sum(1 for v in vals if v < current) / len(vals), 1)
    out["meaningful"] = len(vals) >= min_rows
    return out
