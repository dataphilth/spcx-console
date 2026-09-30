"""Relative-volume block and the incomplete-bar guard. Synthetic data only; no live config."""

from __future__ import annotations

import datetime as dt

from spcx.tape import prices, volume


def _bars(n: int, v: float = 50e6, end: dt.date = dt.date(2026, 9, 29)) -> list[dict]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": v})
        d -= dt.timedelta(days=1)
    return sorted(out, key=lambda b: b["date"])


def test_heavy_session_with_nothing_scheduled_needs_explaining():
    bars = _bars(70)
    bars[-1].update(volume=100e6, close=104.0)
    p = volume.profile(bars, atr=4.0, catalysts=[])
    assert p["rvol20"] == 2.0 and p["rvol60"] == 2.0 and p["label"] == "very heavy"
    assert p["heaviest_on_record"] and p["rank_in_window"] == 1
    assert p["chg_1d_pct"] == 4.0 and p["move_atr"] == 1.0
    assert p["calendar"] == [] and p["needs_explaining"] is True
    assert p["baseline_thin"] is False


def test_scheduled_catalyst_explains_the_volume():
    bars = _bars(70)
    bars[-1]["volume"] = 100e6
    cats = [{"date": dt.date(2026, 9, 29), "event": "Lockup tranche", "kind": "lockup"}]
    p = volume.profile(bars, atr=4.0, catalysts=cats)
    assert p["calendar"][0]["kind"] == "lockup" and p["needs_explaining"] is False


def test_weekend_catalyst_lands_on_the_next_session():
    bars = _bars(30, end=dt.date(2026, 10, 26))           # Monday
    cats = [{"date": dt.date(2026, 10, 24), "event": "Saturday tranche", "kind": "lockup"}]
    assert volume.profile(bars, None, cats)["calendar"][0]["event"] == "Saturday tranche"


def test_expiry_calendar():
    assert volume.third_friday(2026, 9) == dt.date(2026, 9, 18)
    quad = volume.calendar_for(dt.date(2026, 9, 18), dt.date(2026, 9, 17), [])
    assert "quad witching" in quad[0]["event"]
    monthly = volume.calendar_for(dt.date(2026, 10, 16), dt.date(2026, 10, 15), [])
    assert monthly[0]["event"] == "Monthly options expiration"


def test_baseline_excludes_the_session_and_multi_day_windows():
    bars = _bars(40)
    for b in bars[-3:]:
        b["volume"] = 75e6
    p = volume.profile(bars, None, [])
    assert p["rvol20"] == 1.43 and p["rvol_3d"] == 1.5 and p["shares_3d"] == 225_000_000
    assert p["rvol60"] is None and p["baseline_thin"] is True
    assert p["needs_explaining"] is True


def test_light_and_ordinary_labels():
    assert volume.label(0.5) == "light" and volume.label(1.0) == "ordinary" and volume.label(3.5) == "extreme"
    assert volume.label(None) is None


def test_row_rejects_missing_prices():
    nan, inf = float("nan"), float("inf")
    assert prices._row("2026-09-29", 1, 2, 1, nan, 5) is None
    assert prices._row("2026-09-29", 1, 2, 1, inf, 5) is None
    assert prices._row("2026-09-29", 1, 2, 1, 1.5, nan) is None
    assert prices._row("2026-09-29", 1, 2, 1, 1.5, 5)["close"] == 1.5


def test_incomplete_bar_is_dropped_loudly(tmp_path, monkeypatch):
    good = _bars(25, end=dt.date(2026, 9, 28))

    def fake_yf(ticker, dropped=None):
        raw = [(b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in good]
        raw.append(("2026-09-29", 100.0, 101.0, 99.0, float("nan"), 79_711_331))
        return prices._clean(raw, dropped)

    monkeypatch.setattr(prices, "fetch_yfinance", fake_yf)
    bars, meta = prices.get_bars("SPCX", tmp_path / "prices.csv", today=dt.date(2026, 9, 30))
    assert bars[-1]["date"] == "2026-09-28"
    assert meta["dropped_bars"] == ["2026-09-29"]
    assert "nan" not in (tmp_path / "prices.csv").read_text().lower()
