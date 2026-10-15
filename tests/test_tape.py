"""The tape layer: pure-Python measurements, symmetric setups.

No network, no pandas. Bars are synthetic and shaped like SPCX's real path
(IPO 135 → 225.64 → 104.83 → ~138) so ATH/ATL assertions are meaningful.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from spcx.tape import setups, technical
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
    t = technical.compute(synthetic_bars(), PARAMS, 135.0)
    assert t["ath"] == 225.64 and t["atl"] == 104.83
    assert t["close"] == 138.46 and t["bars"] > 45
    assert t["atr"] and t["hv30"] and t["rsi"] is not None and t["sma20"]
    assert t["from_ipo_pct"] == pytest.approx(2.56, abs=0.05)


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


def test_full_offline_tape_run_and_dashboard(tmp_path):
    from spcx.tape import dashboard, prices
    prices.save_cache(synthetic_bars(), tmp_path / "prices.csv")
    board = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    cfg = tape_run.load_tape_config()
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    assert tape["price"]["close"] == 138.46
    for dead in ("ladder", "gate", "position"):
        assert dead not in tape, f"{dead} is a retired key — the tape holds no position"
    assert "position" not in json.dumps(tape).lower().replace("positioning", "")
    assert any(c["kind"] == "starship" for c in tape["catalysts"]["horizon"])
    assert (tmp_path / "tape.json").exists() and (tmp_path / "tape_history.csv").exists()
    assert "PRICE BARS STALE" not in " ".join(tape["meta"]["warnings"])
    html = dashboard.render(board, tape, full_document=True)
    assert html.startswith("<!DOCTYPE html>") and "__TAPE__" in html and "L13" in html and "S5" in html
    body = dashboard.render(board, tape, full_document=False)
    assert body.startswith("<title>") and "<html" not in body
    txt = tape_run.brief(tape)
    assert "ladder" not in txt and "bias audit" in txt
    # a second run on the same bar date dedupes history
    tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 26), cfg=cfg, data_dir=tmp_path, board=board)
    assert len((tmp_path / "tape_history.csv").read_text().strip().splitlines()) == 2


def test_tape_config_carries_no_position():
    cfg = tape_run.load_tape_config()
    assert "position" not in cfg and "ladder" not in cfg
    assert cfg["share_structure"]["public_float_b"] > 0 and cfg["catalysts"]


def _chain(spot, dte, iv_atm=0.9, put_skew=0.08, oi_at=None, nan_at=None):
    """Synthetic call/put lists in the shape _contracts() produces, via the real reducer inputs."""
    from spcx.tape.options import _contracts
    pytest.importorskip("pandas")
    import pandas as pd
    nan = float("nan")
    rows_c, rows_p = [], []
    for k in range(85, 195, 5):
        m = (k - spot) / spot
        iv_c = iv_atm - 0.10 * m           # calls cheapen going up
        iv_p = iv_atm + put_skew + 0.30 * (-m) if m < 0 else iv_atm + put_skew * 0.5  # puts bid going down
        oi = (oi_at or {}).get(k, 100)
        if nan_at and k in nan_at:
            rows_c.append({"strike": k, "impliedVolatility": nan, "bid": nan, "ask": nan, "lastPrice": nan, "openInterest": nan})
        else:
            rows_c.append({"strike": k, "impliedVolatility": iv_c, "bid": 5.0, "ask": 5.4, "lastPrice": 5.2, "openInterest": oi})
        rows_p.append({"strike": k, "impliedVolatility": iv_p, "bid": 5.0, "ask": 5.4, "lastPrice": 5.2, "openInterest": oi})
    return _contracts(pd.DataFrame(rows_c), spot, dte, True), _contracts(pd.DataFrame(rows_p), spot, dte, False)


def test_black_scholes_delta_gamma_sanity():
    from spcx.tape.options import bs_delta_gamma
    d_atm, g_atm = bs_delta_gamma(100, 100, 30, 0.9, True)
    assert 0.5 < d_atm < 0.6                      # ATM call delta ~0.55 at high vol
    dp, _ = bs_delta_gamma(100, 100, 30, 0.9, False)
    assert dp == pytest.approx(d_atm - 1.0)      # put-call delta parity with r=0
    _, g_otm = bs_delta_gamma(100, 140, 30, 0.9, True)
    assert g_atm > g_otm > 0                      # gamma peaks near the money


def test_reduce_chain_structure_fields():
    from spcx.tape.options import reduce_chain
    spot = 138.0
    exps = []
    for exp, dte in (("2026-08-28", 3), ("2026-09-18", 24), ("2026-10-16", 52), ("2026-12-18", 115)):
        c, p = _chain(spot, dte, oi_at={140: 5000, 120: 4000}, nan_at={145})
        exps.append((exp, dte, c, p))
    snap = reduce_chain(exps, spot, date(2026, 8, 25))
    assert snap["n_expiries"] == 4 and len(snap["term"]) == 4
    assert 80 < snap["iv30"] < 100 and 80 < snap["iv90"] < 100
    assert snap["skew25_30d"] is not None and snap["skew25_30d"] > 5   # puts were built rich
    assert snap["oi_walls"]["calls"][0]["strike"] == 140 and snap["oi_walls"]["puts"][0]["strike"] == 140
    assert snap["put_call_oi"] == pytest.approx(1.0, abs=0.05)
    assert isinstance(snap["gex_musd_per_1pct"], float)
    assert snap["expected_move_pct"] and snap["front_expiry"] == "2026-08-28"


def test_reduce_chain_survives_nan_and_empty_sides():
    from spcx.tape.options import reduce_chain
    c, p = _chain(138.0, 24, nan_at={135, 140})
    snap = reduce_chain([("2026-09-18", 24, c, p), ("2026-09-04", 10, [], [])], 138.0, date(2026, 8, 25))
    assert snap["iv30"] is not None and snap["n_expiries"] == 1
    with pytest.raises(RuntimeError):
        reduce_chain([("2026-09-18", 24, [], [])], 138.0, date(2026, 8, 25))


def test_iv_history_is_backward_compatible(tmp_path):
    """Older rows have fewer columns; new rows have more. Both must read and rank."""
    from spcx.tape import options
    p = tmp_path / "iv.csv"
    p.write_text("date,spot,iv_front,iv30,iv90,front_expiry,front_dte,expected_move_usd,expected_move_pct,put_call_oi,n_expiries\n"
                 "2026-08-25,138.11,50.0,54.9,60.0,2026-08-28,3,6.2,4.5,1.11,8\n")
    options.append_history({"date": "2026-08-26", "spot": 140.0, "iv30": 65.0, "skew25_30d": 9.5, "term": [{"x": 1}]}, p)
    hist = options.load_history(p)
    assert len(hist) == 2 and hist[1]["skew25_30d"] == "9.5" and hist[0].get("skew25_30d") in (None, "")
    assert options.iv_change(hist, "2026-08-26") == pytest.approx(10.1)
    assert options.rank(hist, 65.0, 60)["iv_percentile"] == 50.0


def test_short_interest_uses_public_float(tmp_path):
    """Yahoo's % is against 13.18B outstanding; the tape restates it against the 1.55B public float."""
    from spcx.tape import options, prices
    prices.save_cache(synthetic_bars(), tmp_path / "prices.csv")
    options.append_history({"date": "2026-08-25", "spot": 138.0, "iv30": 54.0, "short_shares_m": 435.0, "short_pct_float": 3.3,
                            "short_days_to_cover": 2.9, "short_as_of": "2026-07-30"}, tmp_path / "iv_history.csv")
    board = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    cfg = tape_run.load_tape_config()
    cfg["share_structure"]["public_float_b"] = 1.55  # pinned here so this test never depends on the live float in config/tape.yaml
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    assert tape["vol"]["short_pct_public_float"] == pytest.approx(28.1, abs=0.1)
    assert tape["vol"]["short_pct_outstanding"] == 3.3


# ---- moving-average levels -------------------------------------------------------

def _bars_from_closes(closes, start=date(2026, 1, 5)):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1_000_000})
        d += timedelta(days=1)
    return out


def test_ma_series_is_a_true_sma_once_the_window_fills():
    from spcx.tape.levels import ma_series
    closes = [float(i) for i in range(1, 11)]
    ma = ma_series(closes, 3)
    assert ma[0] == 1.0 and ma[1] == 1.5          # partial: averages what exists
    assert ma[-1] == pytest.approx(9.0)           # full: mean of 8, 9, 10


def test_short_history_marks_the_200_partial_and_refuses_the_golden_cross():
    from spcx.tape import levels
    lv = levels.analyze(_bars_from_closes([100.0] * 86), {"windows": [50, 200]})
    l50, l200 = lv["lines"]
    assert l50["full"] and not l200["full"] and l200["have"] == 86 and l200["fills_on"]
    assert lv["pair"]["callable"] is False and lv["pair"]["state"] is None
    assert not any(e["kind"] in ("golden_cross", "death_cross") for e in lv["events"])
    assert "not callable" in levels.state_line(lv)


def test_fresh_cross_up_and_down_fire_symmetric_setups():
    from spcx.tape import levels
    base = [100.0] * 60
    up = levels.analyze(_bars_from_closes(base[:-1] + [90.0] * 5 + [110.0]), {"windows": [50]})
    down = levels.analyze(_bars_from_closes(base[:-1] + [110.0] * 5 + [90.0]), {"windows": [50]})
    (eu,), (ed,) = up["events"], down["events"]
    assert eu["dir"] == "up" and ed["dir"] == "down" and eu["full"] and ed["full"]
    su, sd = levels.to_setups(up), levels.to_setups(down)
    assert [s["id"] for s in su] == ["CROSS_UP_SMA50"] and [s["id"] for s in sd] == ["CROSS_DOWN_SMA50"]
    assert su[0]["direction"] == "bullish" and sd[0]["direction"] == "bearish"
    assert su[0]["strength"] == sd[0]["strength"]
    for s in su + sd:
        assert s["long_read"] and s["short_read"] and s["tag"] == "levels"
    assert levels.notice_markdown([up], "SPCX").startswith("## SPCX")


def test_cross_on_a_partial_window_is_labelled_partial():
    from spcx.tape import levels
    lv = levels.analyze(_bars_from_closes([100.0] * 80 + [90.0] * 5 + [120.0]), {"windows": [200]})
    (e,) = lv["events"]
    assert not e["full"] and e["have"] == 86
    (s,) = levels.to_setups(lv)
    assert s["strength"] == 1 and "PARTIAL WINDOW" in s["evidence"]
    assert "Partial window" in levels.notice_markdown([lv], "SPCX")


def test_failed_cross_is_reported_as_failed():
    from spcx.tape import levels
    lv = levels.analyze(_bars_from_closes([100.0] * 59 + [90.0, 110.0, 90.0, 90.0]), {"windows": [50], "cross_lookback": 5})
    x = lv["lines"][0]["last_cross"]
    assert x["dir"] == "down" and x["held"] is True     # the latest cross is the slip back under
    assert not lv["events"]                              # nothing fresh on the last bar
    lv2 = levels.analyze(_bars_from_closes([100.0] * 59 + [90.0, 110.0, 90.0]), {"windows": [50]})
    assert lv2["events"][0]["reverses_cross_on"]       # the slip back under names the reclaim it undid


def test_golden_and_death_cross_fire_only_with_full_windows():
    from spcx.tape import levels
    closes = [60.0 + 0.2 * i for i in range(200)] + [100.0 - i for i in range(1, 40)] + [70.0 + 3 * i for i in range(1, 60)]
    bars = _bars_from_closes(closes)
    kinds = []
    for k in range(201, len(bars) + 1):
        kinds += [e["kind"] for e in levels.analyze(bars[:k], {"windows": [50, 200]})["events"]
                  if e["kind"] in ("golden_cross", "death_cross")]
    assert kinds == ["death_cross", "golden_cross"]
    s = levels.to_setups({"timeframe": "1D", "events": [{"kind": "golden_cross", "fast": 50, "slow": 200, "fast_ma": 1,
                                                          "slow_ma": 1, "close": 1, "full": True}]})
    assert s[0]["id"] == "GOLDEN_CROSS" and "tops" in s[0]["short_read"]


def test_tape_run_writes_levels_and_clears_stale_notice(tmp_path):
    from spcx.tape import prices
    prices.save_cache(synthetic_bars(), tmp_path / "prices.csv")
    (tmp_path / "notice.md").write_text("stale from yesterday")
    board = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    cfg = tape_run.load_tape_config()
    cfg["ma_events"] = {"windows": [50, 200], "golden_pair": [50, 200], "cross_lookback": 5}  # pinned, not read from live config
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    (lv,) = tape["levels"]
    assert lv["timeframe"] == "1D" and [ln["window"] for ln in lv["lines"]] == [50, 200]
    assert lv["pair"]["callable"] is False
    assert (tmp_path / "notice.md").exists() == bool(lv["events"])
    assert "levels 1D" in tape_run.brief(tape)


# ---- 4H, extended hours -----------------------------------------------------------

def _hourly(days: int, start=date(2026, 9, 1), base=100.0, drift=0.0):
    """Hourly extended-hours bars stamped the way yfinance stamps them in US/Eastern:
    04:00-09:00 pre-market on the hour, 09:30-15:30 regular, 16:00-19:00 post-market."""
    stamps = ["04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "09:30", "10:30", "11:30", "12:30",
              "13:30", "14:30", "15:30", "16:00", "17:00", "18:00", "19:00"]
    out, d, px = [], start, base
    while len([1 for _ in out]) < days * len(stamps):
        if d.weekday() < 5:
            for hhmm in stamps:
                px += drift
                out.append({"ts": f"{d.isoformat()}T{hhmm}", "open": px, "high": px + 0.5, "low": px - 0.5,
                            "close": px, "volume": 1000})
        d += timedelta(days=1)
    return out


def test_aggregate_4h_tiles_the_extended_session_into_four_bars():
    from datetime import datetime

    from spcx.tape.levels import aggregate_4h
    h = _hourly(1, drift=1.0)
    bars = aggregate_4h(h)
    assert [b["date"][11:] for b in bars] == ["04:00", "08:00", "12:00", "16:00"]
    am = bars[1]                                   # 08:00, 09:00, 09:30, 10:30, 11:30
    assert am["open"] == h[4]["open"] and am["close"] == h[8]["close"] and am["volume"] == 5000
    assert am["high"] == max(r["high"] for r in h[4:9])
    # the post-market bucket is still building at 17:30 ET -> dropped
    live = aggregate_4h(h, now=datetime.fromisoformat(h[0]["ts"][:10] + "T17:30"))
    assert [b["date"][11:] for b in live] == ["04:00", "08:00", "12:00"]


def test_4h_reports_the_latest_cross_among_a_days_new_bars():
    from spcx.tape import levels
    closes = [95.0 + 0.1 * i for i in range(60)] + [90.0, 110.0, 111.0, 112.0]   # down then back up, 3 bars before the end
    bars = [{"date": f"2026-09-{1 + i // 4:02d}T{4 + 4 * (i % 4):02d}:00", "close": c} for i, c in enumerate(closes)]
    lv = levels.analyze(bars, {"windows": [50]}, timeframe="4H", fresh_bars=4, bars_per_day=4)
    (e,) = lv["events"]
    assert e["dir"] == "up" and e["date"] == bars[-3]["date"] and e["held_since"] is True
    assert e["crosses_in_window"] == 2                     # down at 90, back up at 110
    (s,) = levels.to_setups(lv)
    assert s["id"] == "CROSS_UP_SMA50_4H" and "50-bar" in s["name"] and "chop" in s["evidence"]
    # the daily keeps a one-bar fresh window, so the same shape a few bars back fires nothing
    assert not levels.analyze(bars, {"windows": [50]}, timeframe="1D")["events"]


def test_4h_fill_date_counts_four_bars_a_day():
    from spcx.tape.levels import _sessions_until_full
    assert _sessions_until_full(192, 200, "2026-10-14T16:00", bars_per_day=4) == "2026-10-16"
    assert _sessions_until_full(200, 200, "2026-10-14T16:00", bars_per_day=4) is None


def test_tape_run_adds_extended_hours_4h_levels(tmp_path):
    from spcx.tape import prices
    prices.save_cache(synthetic_bars(), tmp_path / "prices.csv")
    import csv
    with open(tmp_path / "prices_1h.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=prices.H_COLUMNS)
        w.writeheader()
        w.writerows(_hourly(60, start=date(2026, 6, 15), base=140.0, drift=0.01))
    board = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    cfg = tape_run.load_tape_config()
    cfg["ma_events"] = {"windows": [50, 200], "golden_pair": [50, 200], "cross_lookback": 5,
                        "intraday_4h": {"enabled": True, "extended_hours": True, "fresh_bars": 4}}
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    d1, h4 = tape["levels"]
    assert d1["timeframe"] == "1D" and h4["timeframe"] == "4H" and h4["extended_hours"]
    assert h4["bars"] == 240 and all(ln["full"] for ln in h4["lines"]) and h4["pair"]["callable"]
    assert "levels 4H (ext hours)" in tape_run.brief(tape)
    assert not any(w.startswith("4H LEVELS") for w in tape["meta"]["warnings"])
    # regular-hours-only switch drops pre/post bars
    cfg["ma_events"]["intraday_4h"]["extended_hours"] = False
    tape = tape_run.run("SPCX", 135.0, offline=True, today=date(2026, 8, 25), cfg=cfg, data_dir=tmp_path, board=board)
    assert tape["levels"][1]["bars"] == 120 and not tape["levels"][1]["lines"][1]["full"]


def test_hourly_cache_rejects_incomplete_rows(tmp_path):
    from spcx.tape import prices
    p = tmp_path / "h.csv"
    p.write_text("ts,open,high,low,close,volume\n2026-10-14T04:00,1,2,0.5,1.5,10\n2026-10-14T05:00,1,2,0.5,nan,10\n")
    rows, meta = prices.get_hourly("SPCX", p, offline=True)
    assert [r["ts"] for r in rows] == ["2026-10-14T04:00"] and meta["source"] == "cache (offline)"
