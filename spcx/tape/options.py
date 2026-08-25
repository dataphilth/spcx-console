"""Options structure from the listed chain (yfinance, optional). Context only.

Per run the whole chain (first `max_expiries` expiries) is reduced to:

  iv30 / iv90         ATM implied vol interpolated in total variance to constant maturity
  iv_front            ATM IV of the nearest expiry with >= 3 DTE
  expected_move       front-expiry ATM straddle, $ and %
  term                [(expiry, dte, atm_iv)] — the full term structure
  skew25_front/_30d   25-delta put IV minus 25-delta call IV (points). Positive = puts bid.
  oi_walls            largest open-interest strikes, calls and puts, expiries <= 60 DTE
  put_call_oi         total put OI / total call OI
  gex_musd_per_1pct   dealer-gamma proxy: Σ gamma·OI·100·S²·1% (calls +, puts −), $M.
                      Assumes dealers are long calls / short puts, the usual convention.
                      A crude sign-and-size estimate, not a positioning feed.
  short_*             shares short, % of float, days-to-cover, as-of — Yahoo's copy of the
                      exchange-reported bi-monthly figure (medium confidence).

Delta and gamma are Black-Scholes with r=0 using each contract's own IV, which is
Yahoo's calc on a thin, young, 90-vol name. Treat every number here as ±5 vol points
and every OI figure as end-of-prior-session. None of this is a criterion.
"""

from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path

IV_COLUMNS = ["date", "spot", "iv_front", "iv30", "iv90", "front_expiry", "front_dte",
              "expected_move_usd", "expected_move_pct", "put_call_oi", "n_expiries",
              "skew25_front", "skew25_30d", "gex_musd_per_1pct", "total_call_oi", "total_put_oi",
              "short_pct_float", "short_shares_m", "short_days_to_cover", "short_as_of"]


def _f(x, default: float = 0.0) -> float:
    """float() that treats None / NaN / unparsable as `default`. Yahoo chains are full of NaN cells."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) else v


# ---- Black-Scholes, r = 0, q = 0 ---------------------------------------------------------

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_delta_gamma(spot: float, strike: float, dte: int, iv: float, is_call: bool) -> tuple[float, float]:
    """(delta, gamma) with r=0. iv as a decimal (0.9 = 90 vol)."""
    t = max(dte, 1) / 365.0
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0, 0.0
    s = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / s
    delta = _ncdf(d1) if is_call else _ncdf(d1) - 1.0
    gamma = _npdf(d1) / (spot * s)
    return delta, gamma


# ---- chain reduction ------------------------------------------------------------------------

def _contracts(chain, spot: float, dte: int, is_call: bool) -> list[dict]:
    """One dict per usable contract: strike, iv, oi, mid, delta, gamma."""
    if chain is None or len(chain) == 0 or "strike" not in chain:
        return []
    out = []
    for r in chain.to_dict("records"):
        k = _f(r.get("strike"), float("nan"))
        if math.isnan(k) or k <= 0:
            continue
        iv = _f(r.get("impliedVolatility"), float("nan"))
        iv = iv if not math.isnan(iv) and 0.05 < iv < 5 else None
        bid, ask, last = (_f(r.get(c)) for c in ("bid", "ask", "lastPrice"))
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else (last if last > 0 else None)
        oi = int(_f(r.get("openInterest")))
        delta = gamma = None
        if iv is not None:
            delta, gamma = bs_delta_gamma(spot, k, dte, iv, is_call)
        out.append({"strike": k, "iv": iv, "oi": oi, "mid": mid, "delta": delta, "gamma": gamma, "is_call": is_call})
    return out


def _atm(contracts: list[dict], spot: float) -> tuple[float | None, float | None, int]:
    """(atm_iv, mid, total_oi) for one side."""
    if not contracts:
        return None, None, 0
    row = min(contracts, key=lambda c: abs(c["strike"] - spot))
    return row["iv"], row["mid"], sum(c["oi"] for c in contracts)


def _iv_at_delta(contracts: list[dict], target: float) -> float | None:
    """IV of the contract whose |delta| is nearest `target` (0.25 for the wings)."""
    cands = [c for c in contracts if c["iv"] is not None and c["delta"] is not None]
    if not cands:
        return None
    row = min(cands, key=lambda c: abs(abs(c["delta"]) - target))
    if abs(abs(row["delta"]) - target) > 0.12:   # nothing near 25Δ listed — don't fake it
        return None
    return row["iv"]


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


def reduce_chain(expiries: list[tuple[str, int, list[dict], list[dict]]], spot: float, today: date) -> dict:
    """Pure reduction of [(expiry, dte, calls, puts)] → snapshot fields. Testable without yfinance."""
    points: list[tuple[int, float]] = []
    term: list[dict] = []
    front = None
    c_oi = p_oi = 0
    skews: list[tuple[int, float]] = []
    walls_c: dict[float, int] = {}
    walls_p: dict[float, int] = {}
    gex = 0.0
    for exp, dte, calls, puts in expiries:
        if dte < 3:
            continue
        civ, cmid, coi = _atm(calls, spot)
        piv, pmid, poi = _atm(puts, spot)
        c_oi, p_oi = c_oi + coi, p_oi + poi
        ivs = [v for v in (civ, piv) if v is not None]
        if not ivs:
            continue
        atm = sum(ivs) / len(ivs)
        points.append((dte, atm))
        term.append({"expiry": exp, "dte": dte, "atm_iv": round(atm * 100, 1)})
        p25, c25 = _iv_at_delta(puts, 0.25), _iv_at_delta(calls, 0.25)
        if p25 is not None and c25 is not None:
            skews.append((dte, (p25 - c25) * 100))
        if dte <= 60:
            for c in calls:
                walls_c[c["strike"]] = walls_c.get(c["strike"], 0) + c["oi"]
            for c in puts:
                walls_p[c["strike"]] = walls_p.get(c["strike"], 0) + c["oi"]
        for c in calls + puts:
            if c["gamma"]:
                sign = 1.0 if c["is_call"] else -1.0
                gex += sign * c["gamma"] * c["oi"] * 100 * spot * spot * 0.01
        if front is None:
            front = {"expiry": exp, "dte": dte, "iv": atm, "straddle": (cmid + pmid) if cmid and pmid else None}
    points.sort()
    if not points:
        raise RuntimeError("no usable ATM IV points")
    iv30, iv90 = _interp(points, 30), _interp(points, 90)
    em = front["straddle"] if front else None
    skew_front = skews[0][1] if skews else None
    skew_30 = min(skews, key=lambda s: abs(s[0] - 30))[1] if skews else None
    top = lambda d: [{"strike": k, "oi": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:3]]  # noqa: E731
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
        "term": term,
        "skew25_front": round(skew_front, 1) if skew_front is not None else None,
        "skew25_30d": round(skew_30, 1) if skew_30 is not None else None,
        "oi_walls": {"calls": top(walls_c), "puts": top(walls_p), "window_dte": 60},
        "total_call_oi": c_oi, "total_put_oi": p_oi,
        "gex_musd_per_1pct": round(gex / 1e6, 1),
    }


def fetch_snapshot(ticker: str, spot: float, today: date, max_expiries: int = 8) -> dict:
    """Pull the chain via yfinance and reduce it. Raises on failure (the caller records a warning)."""
    import yfinance as yf  # optional

    t = yf.Ticker(ticker)
    listed = list(t.options or [])
    if not listed:
        raise RuntimeError("no listed expiries")
    expiries = []
    for exp in listed[:max_expiries]:
        dte = (date.fromisoformat(exp) - today).days
        if dte < 3:
            continue
        try:
            oc = t.option_chain(exp)
        except Exception:  # noqa: BLE001
            continue
        expiries.append((exp, dte, _contracts(oc.calls, spot, dte, True), _contracts(oc.puts, spot, dte, False)))
    snap = reduce_chain(expiries, spot, today)
    snap.update(fetch_short_interest(t))
    return snap


def fetch_short_interest(t) -> dict:
    """Yahoo's copy of the exchange-reported bi-monthly short interest. Medium confidence; may be absent."""
    out = {"short_pct_float": None, "short_shares_m": None, "short_days_to_cover": None, "short_as_of": None}
    try:
        info = t.info or {}
    except Exception:  # noqa: BLE001
        return out
    pf = _f(info.get("shortPercentOfFloat"), float("nan"))
    sh = _f(info.get("sharesShort"), float("nan"))
    dtc = _f(info.get("shortRatio"), float("nan"))
    ts = info.get("dateShortInterest")
    out["short_pct_float"] = round(pf * 100, 1) if not math.isnan(pf) else None
    out["short_shares_m"] = round(sh / 1e6, 1) if not math.isnan(sh) else None
    out["short_days_to_cover"] = round(dtc, 1) if not math.isnan(dtc) else None
    try:
        out["short_as_of"] = date.fromtimestamp(int(ts)).isoformat() if ts else None
    except (TypeError, ValueError, OSError):
        out["short_as_of"] = None
    return out


# ---- history ----------------------------------------------------------------------------------

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
        w = csv.DictWriter(fh, fieldnames=IV_COLUMNS, extrasaction="ignore")
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


def iv_change(history: list[dict], current_date: str, field: str = "iv30") -> float | None:
    """Day-over-day change in `field` (points) against the most recent prior row."""
    prior = [r for r in history if r["date"] < current_date and r.get(field) not in (None, "")]
    cur = [r for r in history if r["date"] == current_date and r.get(field) not in (None, "")]
    if not prior or not cur:
        return None
    try:
        return round(float(cur[-1][field]) - float(prior[-1][field]), 1)
    except (TypeError, ValueError):
        return None
