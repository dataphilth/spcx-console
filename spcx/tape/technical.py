"""Price-derived measurements, pure Python. Nothing here is a recommendation.

With ~50 sessions of history most windows are barely warm; `bars` in the output
says how many the run had, and the setups layer attaches a caveat under 40.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def _true_ranges(bars: list[dict]) -> list[float]:
    out = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b["high"] - b["low"])
            continue
        pc = bars[i - 1]["close"]
        out.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
    return out


def atr(bars: list[dict], window: int) -> float | None:
    tr = _true_ranges(bars)
    need = max(3, window // 2)
    if len(tr) < need:
        return None
    return mean(tr[-window:])


def realized_vol(closes: list[float], window: int) -> float | None:
    lr = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    need = max(5, window // 2)
    if len(lr) < need:
        return None
    w = lr[-window:]
    if len(w) < 2:
        return None
    m = mean(w)
    var = sum((x - m) ** 2 for x in w) / (len(w) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def sma(closes: list[float], window: int) -> float | None:
    need = max(5, window // 2)
    if len(closes) < need:
        return None
    return mean(closes[-window:])


def rsi(closes: list[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = mean(gains[:window]), mean(losses[:window])
    for gain, loss in zip(gains[window:], losses[window:]):
        ag = (ag * (window - 1) + gain) / window
        al = (al * (window - 1) + loss) / window
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def compute(bars: list[dict], params: dict, cost_basis: float | None, ipo_price: float | None) -> dict:
    bars = sorted(bars, key=lambda b: b["date"])
    n = len(bars)
    closes = [b["close"] for b in bars]
    last = bars[-1]
    close = last["close"]
    out: dict = {"bars": n, "date": last["date"], "close": _r(close)}

    if n >= 2:
        out["chg_1d_pct"] = _r(100 * (close / closes[-2] - 1))
    for k in (5, 20):
        if n > k:
            out[f"chg_{k}d_pct"] = _r(100 * (close / closes[-1 - k] - 1))

    a = atr(bars, params["atr_window"])
    out["atr"] = _r(a)
    out["atr_pct"] = _r(100 * a / close) if a else None

    for w in params["hv_windows"]:
        out[f"hv{w}"] = _r(realized_vol(closes, w), 1)

    for w in params["sma_windows"]:
        s = sma(closes, w)
        out[f"sma{w}"] = _r(s)
        if s and a:
            out[f"dist_sma{w}_atr"] = _r((close - s) / a)
            out[f"dist_sma{w}_pct"] = _r(100 * (close / s - 1))

    out["rsi"] = _r(rsi(closes, params["rsi_window"]), 1)

    rw = params["range_window"]
    if n >= 3:
        win = bars[-rw:]
        hi, lo = max(b["high"] for b in win), min(b["low"] for b in win)
        out["range_high"], out["range_low"] = _r(hi), _r(lo)
        out["range_pos"] = _r((close - lo) / (hi - lo)) if hi > lo else None
        if n > rw:
            prior = bars[-rw - 1:-1]
            out["prior_range_high"] = _r(max(b["high"] for b in prior))
            out["prior_range_low"] = _r(min(b["low"] for b in prior))
        if n >= 2 * rw:
            prior = bars[-2 * rw:-rw]
            prng = max(b["high"] for b in prior) - min(b["low"] for b in prior)
            out["range_compression"] = _r((hi - lo) / prng) if prng > 0 else None

    vz = params["volume_z_window"]
    if n > vz:
        vols = [float(b["volume"]) for b in bars[-vz - 1:-1]]
        mu, sd = mean(vols), pstdev(vols)
        out["volume"] = int(last["volume"])
        out["volume_z"] = _r((last["volume"] - mu) / sd) if sd > 0 else None
        out["volume_vs_avg"] = _r(last["volume"] / mu) if mu else None

    hi_bar = max(bars, key=lambda b: b["high"])
    lo_bar = min(bars, key=lambda b: b["low"])
    out.update(ath=_r(hi_bar["high"]), ath_date=hi_bar["date"], atl=_r(lo_bar["low"]), atl_date=lo_bar["date"])
    out["from_ath_pct"] = _r(100 * (close / hi_bar["high"] - 1))
    out["from_atl_pct"] = _r(100 * (close / lo_bar["low"] - 1))
    if cost_basis:
        out["from_basis_pct"] = _r(100 * (close / cost_basis - 1))
    if ipo_price:
        out["from_ipo_pct"] = _r(100 * (close / ipo_price - 1))

    if n >= 2:
        out["gap_pct"] = _r(100 * (last["open"] / closes[-2] - 1))
        rng = last["high"] - last["low"]
        out["close_loc"] = _r((close - last["low"]) / rng) if rng > 0 else None

    streak = 0
    for i in range(n - 1, 0, -1):
        d = closes[i] - closes[i - 1]
        s = 1 if d > 0 else -1 if d < 0 else 0
        if s == 0 or (streak and (s > 0) != (streak > 0)):
            break
        streak += s
    out["streak"] = streak
    return out


def chart_series(bars: list[dict], n: int) -> list[dict]:
    return [{"d": b["date"], "c": round(b["close"], 2), "h": round(b["high"], 2), "l": round(b["low"], 2),
             "v": int(b["volume"])} for b in sorted(bars, key=lambda b: b["date"])[-n:]]
