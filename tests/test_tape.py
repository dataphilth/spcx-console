"""The tape layer: pure-Python measurements, symmetric setups, ladder gating.

No network, no pandas. Bars are synthetic and shaped like SPCX's real path
(IPO 135 → 225.64 → 104.83 → ~138) so ATH/ATL assertions are meaningful.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from spcx.tape import ladder, setups, technical
from spcx.tape import run as tape_run

ROOT = Path(__file__).resolve().parent.parent


def synthetic_bars(end: date = date(2026, 8, 25), seed: int = 7) -> list[dict]:
    anchors = [(date(2026, 6, 15), 171.7), (date(2026, 6, 16), 201.8), (date(2026, 7, 10), 145.3),
               (date(2026, 8, 3), 114.5), (date(2026, 8, 14), 140.0), (end, 138.46)]
    rng = random.Random(seed)
    d, bars, prev = anchors[0][0], [], None
    while d <= end:
        if d.weekday() < 5:
            # linear interpolation between anchors
            for (d0, v0), (d1, v1) in zip(anchors, anchors[1:]):
                if d0 <= d <= d1:
                    c = v0 + (v1 - v0) * (d - d0).days / max((d1 - d0).days, 1)
                    break
            o = prev * (1 + rng.gauss(0, 0.015)) if prev else 171.74
            hi = max(o, c) * (1 + abs(rng.gauss(0, 0.02)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, 0.02)))
            bars.append({"date": d.isoformat(), "open": round(o, 2), "high": round(min(hi, 225.64), 2),
                         "low": round(max(lo, 104.83), 2), "close": round(c, 2), "volume": int(abs(rng.gauss(60e6, 20e6)) + 5e6)})
            prev = c
        d += timedelta(days=1)
    bars[1]["high"] = 225.64
    bars[[b["date"] for b in bars].index("2026-08-03")]["low"] = 104.83
    return bars


PARAMS = {"atr_window": 20, "hv_windows": [10, 30], "sma_windows": [20, 50], "rsi_window": 14, "range_window": 20,
          "volume_z_window": 20, "extreme_atr_multiple": 2.0, "volume_climax_z": 2.5, "iv_hv_rich_spread": 15,
          "iv_hv_cheap_spread": -15, "min_history_for_ivrank": 60, "catalyst_lookahead_days": 10}


def test_technical_measures_the_real_extremes():
    t = technical.compute(synthetic_bars(), PARAMS, 137.85, 135.0)
    assert t["ath"] == 225.64 and t["atl"] == 104.83
    assert t["close"] == 138.46 and t["bars"] > 45
    assert t["atr"] and t["hv30"] and t["rsi"] is not None and t["sma20"]
    assert t["from_basis_pct"] == pytest.approx(0.44, abs=0.05)


def test_every_setup_carries_both_reads():
    base = {"bars": 60, "close": 100.0, "atr": 5.0, "sma20": 100.0, "sma50": 100.0, "rsi": 50,
            "prior_range_high": 110, "prior_range_low": 90}
    down = setups.detect({**base, "dist_sma20_atr": -2.5, "rsi": 25, "close": 85.0}, {}, PARAMS, [])
    up = setups.detect({**base, "dist_sma20_atr": 2.5, "rsi": 75, "close": 115.0}, {}, PARAMS, [])
    assert {"STRETCH_DOWN", "RSI_OVERSOLD", "BREAKDOWN_20D"} <= {s["id"] for s in down}
    assert {"STRETCH_UP", "RSI_OVERBOUGHT", "BREAKOUT_20D"} <= {s["id"] for s in up}
    for s in down + up:
        assert s["long_read"] and s["short_read"]
    # symmetric thresholds produce symmetric label counts
    assert sum(s["direction"] == "bullish" for s in down) == sum(s["direction"] == "bearish" for s in up)


def test_vol_setups_need_a_real_spread():
    base = {"bars": 60, "close": 100.0, "atr": 5.0, "sma20": 100.0, "rsi": 50}
    assert not any(s["tag"] == "vol" for s in setups.detect(base, {"iv_hv_spread": None}, PARAMS, []))
    cheap = setups.detect(base, {"iv30": 60, "hv30": 90, "iv_hv_spread": -30}, PARAMS, [])
    assert any(s["id"] == "PREMIUM_CHEAP" for s in cheap)


def test_ladder_pauses_on_long_tier1_fired_only():
    bands = [{"name": "A", "low": 130, "high": 145, "shares": 10}, {"name": "B", "low": 100, "high": 130, "shares": 20, "requires_criteria_check": True}]
    ev = lambda cid, case, tier, status: {"criterion_id": cid, "case": case, "tier": tier, "status": status}  # noqa: E731
    open_gate = ladder.gate_from_evaluations([ev("L1", "long", 1, "clear"), ev("S5", "short", 1, "fired")])
    assert not open_gate["paused"], "a fired SHORT-case criterion must not pause the accumulation ladder"
    r = ladder.evaluate(120.0, bands, [], open_gate, [], 5000)
    assert r["active_band"] == "B" and r["requires_criteria_check"] and "20 shares" in r["message"]
    t1 = ladder.gate_from_evaluations([ev("L4", "long", 1, "fired")])
    assert ladder.evaluate(120.0, bands, [], t1, [], 5000)["paused"]
    t2 = ladder.gate_from_evaluations([ev("L8", "long", 2, "fired"), ev("L13", "long", 2, "fired")])
    assert ladder.evaluate(120.0, bands, [], t2, [], 5000)["paused"]
    one_t2 = ladder.gate_from_evaluations([ev("L13", "long", 2, "fired")])
    assert not ladder.evaluate(120.0, bands, [], one_t2, [], 5000)["paused"]
    twice = ladder.evaluate(120.0, bands, [{"band": "B", "price": 115.0}], open_gate, [], 5000)
    assert "repeat rule" in twice["message"]


def test_full_offline_tape_run_and_dashboard(tmp_path):
    from spcx.tape import dashboard, prices
    prices.save_cache(synthetic_bars(), tmp_path / "prices.csv")
    board = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    cfg = tape_run.load_tape_config()
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    assert tape["price"]["close"] == 138.46 and tape["ladder"]["active_band"] == "Current"
    assert tape["gate"]["paused"] is False
    assert any(c["kind"] == "starship" for c in tape["catalysts"]["upcoming"])
    assert (tmp_path / "tape.json").exists() and (tmp_path / "tape_history.csv").exists()
    assert "PRICE BARS STALE" not in " ".join(tape["meta"]["warnings"])
    html = dashboard.render(board, tape, full_document=True)
    assert html.startswith("<!DOCTYPE html>") and "__TAPE__" in html and "L13" in html and "S5" in html
    body = dashboard.render(board, tape, full_document=False)
    assert body.startswith("<title>") and "<html" not in body
    txt = tape_run.brief(tape)
    assert "ladder:" in txt and "bias audit" in txt
    # a second run on the same bar date dedupes history
    tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 26), cfg=cfg, data_dir=tmp_path, board=board)
    assert len((tmp_path / "tape_history.csv").read_text().strip().splitlines()) == 2


def test_tape_config_is_ordered_and_unfunded_by_default():
    cfg = tape_run.load_tape_config()
    bands = cfg["ladder"]["bands"]
    assert all(a["low"] >= b["high"] for a, b in zip(bands, bands[1:]))
    assert cfg["position"]["total_budget_dollars"] == 0  # until Phil funds it


def test_options_atm_survives_nan_cells():
    """Yahoo chains carry NaN open interest / bids on illiquid strikes. Live bug, 2026-08-25."""
    pytest.importorskip("pandas")
    import pandas as pd
    from spcx.tape import options
    nan = float("nan")
    chain = pd.DataFrame([
        {"strike": 130.0, "impliedVolatility": 0.71, "bid": 9.0, "ask": 9.4, "lastPrice": 9.2, "openInterest": nan},
        {"strike": 140.0, "impliedVolatility": 0.68, "bid": nan, "ask": nan, "lastPrice": 5.1, "openInterest": 120},
        {"strike": nan, "impliedVolatility": nan, "bid": nan, "ask": nan, "lastPrice": nan, "openInterest": nan},
    ])
    iv, mid, oi = options._atm(chain, 138.0)
    assert iv == pytest.approx(0.68) and mid == pytest.approx(5.1) and oi == 120
