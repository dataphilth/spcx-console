import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from spcx import forecast


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast, "LOG", tmp_path / "forecasts.yaml")


def test_scoring_penalises_confident_wrongness():
    forecast.add("A happens", 0.95, "2026-12-31")
    forecast.resolve("f0001", False)
    s = forecast.score()
    assert s["brier"] == pytest.approx(0.9025)
    assert s["bias_reading"] == "over-forecasting"


def test_overconfidence_loses_to_the_base_rate():
    """Being mostly right is not the bar.

    Four forecasts at 90% that resolve 3-of-4 true score worse than someone who
    simply said 75% every time. This is the whole reason the log exists: it
    catches confidence that outruns accuracy, which no amount of narrative
    self-review ever will.
    """
    for _ in range(4):
        forecast.add("x", 0.9, "2026-12-31")
    for i, o in enumerate([True, True, True, False], start=1):
        forecast.resolve(f"f{i:04d}", o)
    s = forecast.score()
    assert s["n"] == 4
    assert s["base_rate"] == 0.75
    assert s["brier"] == pytest.approx(0.21)
    assert s["base_rate_brier"] == pytest.approx(0.1875)
    assert s["beats_base_rate"] is False


def test_calibrated_forecasts_do_beat_the_base_rate():
    """Confidence that tracks outcomes is rewarded."""
    for p in (0.95, 0.95, 0.95, 0.1):
        forecast.add("x", p, "2026-12-31")
    for i, o in enumerate([True, True, True, False], start=1):
        forecast.resolve(f"f{i:04d}", o)
    s = forecast.score()
    assert s["beats_base_rate"] is True
    assert s["bias_reading"] == "roughly calibrated"


def test_overdue_surfaces_unresolved_past_deadline():
    forecast.add("stale claim", 0.5, "2020-01-01")
    assert len(forecast.overdue()) == 1
    forecast.resolve("f0001", True)
    assert forecast.overdue() == []


def test_probability_bounds_enforced():
    with pytest.raises(ValueError):
        forecast.add("x", 1.4, "2026-12-31")


def test_no_resolved_forecasts_reports_nothing_rather_than_zero():
    assert forecast.score()["brier"] is None
