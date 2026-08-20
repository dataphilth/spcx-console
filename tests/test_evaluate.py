"""Tests for the evaluation engine.

These target the specific ways this kind of system goes wrong quietly:
streaks manufactured from repeated readings of the same filing, missing data
reported as reassurance, and "close" being promoted to "fired".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from spcx.evaluate import evaluate_one, summarise  # noqa: E402
from spcx.models import Reading, Snapshot  # noqa: E402


def snap(run_date, metric, value, period=None, as_of=None):
    s = Snapshot(run_date=run_date)
    s.add(Reading(metric=metric, value=value, unit="$M", as_of=as_of or run_date,
                  period=period, source="test", source_url="test://",
                  collector="test", confidence="high"))
    return s


THRESH = {
    "id": "T1", "case": "long", "tier": 1, "label": "Test", "condition": "",
    "unit": "$M", "scale": [-600, 2000],
    "rule": {"type": "threshold", "metric": "m", "operator": "lt",
             "threshold": 0, "consecutive": 2},
}


def test_missing_data_is_unknown_not_clear():
    """Absence of evidence must not render as reassurance."""
    e = evaluate_one(THRESH, [], {})
    assert e.status == "unknown"
    assert e.value is None


def test_single_breach_is_nearing_not_fired():
    """A two-quarter condition does not fire on one quarter, however bad."""
    hist = [snap("2026-05-01", "m", 500, period="2026Q1"),
            snap("2026-08-01", "m", -900, period="2026Q2")]
    e = evaluate_one(THRESH, hist, {})
    assert e.status == "nearing"
    assert e.streak == 1


def test_two_consecutive_periods_fire():
    hist = [snap("2026-05-01", "m", -100, period="2026Q1"),
            snap("2026-08-01", "m", -900, period="2026Q2")]
    e = evaluate_one(THRESH, hist, {})
    assert e.status == "fired"
    assert e.streak == 2


def test_streak_dedupes_by_period_not_by_snapshot():
    """The bug that ruins this class of system.

    Reading the same 10-Q every day for ninety days must not produce a
    ninety-quarter streak. One filing is one period, however many times it is
    observed.
    """
    hist = [snap(f"2026-08-{d:02d}", "m", -900, period="2026Q2") for d in range(1, 30)]
    e = evaluate_one(THRESH, hist, {})
    assert e.streak == 1, "29 observations of one quarter is still one quarter"
    assert e.status == "nearing"


def test_restatement_supersedes_rather_than_appends():
    """A corrected figure replaces the original for that period."""
    hist = [snap("2026-08-01", "m", -900, period="2026Q2"),
            snap("2026-09-01", "m", 400, period="2026Q2")]  # restated positive
    e = evaluate_one(THRESH, hist, {})
    assert e.streak == 0
    assert e.status == "clear"


def test_proximity_reported_without_promoting_status():
    """Close is visible but never counted as met."""
    near = dict(THRESH, rule={**THRESH["rule"], "consecutive": 1})
    hist = [snap("2026-08-01", "m", 40, period="2026Q2")]  # threshold 0, scale span 2600
    e = evaluate_one(near, hist, {})
    assert e.status == "nearing"
    assert e.value == 40
    assert 0.95 < e.proximity < 1.0


def test_compare_rule_counts_joint_periods_only():
    """capex > revenue is meaningless in a period where only one was observed."""
    c = {"id": "L13", "case": "long", "tier": 2, "label": "capex over revenue",
         "condition": "", "unit": "quarters",
         "rule": {"type": "compare", "metric": "capex", "operator": "gt",
                  "against": "revenue", "consecutive": 3}}
    s1 = Snapshot(run_date="2026-05-01")
    for m, v in (("capex", 7700), ("revenue", 4700)):
        s1.add(Reading(metric=m, value=v, unit="$M", as_of="2026-05-01", period="2026Q1",
                       source="t", source_url="t://", collector="t"))
    s2 = Snapshot(run_date="2026-08-01")
    for m, v in (("capex", 18369), ("revenue", 7814)):
        s2.add(Reading(metric=m, value=v, unit="$M", as_of="2026-08-01", period="2026Q2",
                       source="t", source_url="t://", collector="t"))
    e = evaluate_one(c, [s1, s2], {})
    assert e.streak == 2
    assert e.status == "nearing", "two of three required quarters is not three"


def test_streak_rule_needs_two_periods():
    c = {"id": "S4", "case": "short", "tier": 2, "label": "capex declines",
         "condition": "", "unit": "quarters",
         "rule": {"type": "streak", "metric": "capex", "direction": "down",
                  "periods": 2, "period_type": "quarter"}}
    one = [snap("2026-08-01", "capex", 18369, period="2026Q2")]
    assert evaluate_one(c, one, {}).status == "unknown"

    rising = [snap("2026-05-01", "capex", 7700, period="2026Q1"),
              snap("2026-08-01", "capex", 18369, period="2026Q2")]
    assert evaluate_one(c, rising, {}).streak == 0


def test_manual_state_passes_through_and_defaults_safely():
    c = {"id": "L6", "case": "long", "tier": 1, "label": "Fatal accident",
         "condition": "", "rule": {"type": "manual", "key": "fatal"}}
    assert evaluate_one(c, [], {}).status == "unknown"
    manual = {"states": {"fatal": {"state": "clear", "detail": "None."}}}
    assert evaluate_one(c, [], manual).status == "clear"
    junk = {"states": {"fatal": {"state": "probably fine", "detail": ""}}}
    assert evaluate_one(c, [], junk).status == "unknown", "unrecognised state is not clear"


def test_summary_separates_the_two_cases():
    """The board must never collapse into a single directional score."""
    class E:
        def __init__(self, i, s, c):
            self.criterion_id, self.status, self.case, self.proximity = i, s, c, None
    evals = [E("L1", "fired", "long"), E("S1", "fired", "short"), E("L2", "clear", "long")]
    s = summarise(evals)
    assert s["long_fired"] == ["L1"]
    assert s["short_fired"] == ["S1"]


def test_reading_rejects_value_without_source():
    with pytest.raises(ValueError):
        Reading(metric="m", value=1, unit="$M", as_of="2026-08-01",
                source="", source_url="", collector="t")


def test_reading_rejects_malformed_date():
    with pytest.raises(ValueError):
        Reading(metric="m", value=1, unit="$M", as_of="August 2026",
                source="t", source_url="t://", collector="t")


DEADLINE = {
    "id": "L8", "case": "long", "tier": 2, "label": "No orbit by the deadline",
    "condition": "", "unit": "flights", "scale": [0, 4],
    "rule": {"type": "threshold", "metric": "orbital", "operator": "lt",
             "threshold": 1, "consecutive": 1, "deadline": "2099-06-30"},
}


def test_deadline_criterion_cannot_fire_before_its_deadline():
    """"Fails to happen by D" is not missed while there is time left on the clock."""
    hist = [snap("2026-08-01", "orbital", 0, period="cumulative")]
    e = evaluate_one(DEADLINE, hist, {})
    assert e.status == "nearing", "on track to fire is not fired"
    assert "remaining" in e.detail


def test_deadline_criterion_fires_once_the_deadline_passes():
    past = dict(DEADLINE, rule={**DEADLINE["rule"], "deadline": "2020-01-01"})
    hist = [snap("2026-08-01", "orbital", 0, period="cumulative")]
    assert evaluate_one(past, hist, {}).status == "fired"


def test_deadline_criterion_clears_if_the_condition_resolved_in_time():
    past = dict(DEADLINE, rule={**DEADLINE["rule"], "deadline": "2020-01-01"})
    hist = [snap("2026-08-01", "orbital", 3, period="cumulative")]
    assert evaluate_one(past, hist, {}).status == "clear"


# ---------------------------------------------------------------------------
# A gap that cannot close must not be reported like one that is merely waiting.

REGISTRY = {"metrics": {
    "m": {"source": "auto", "collector": "sec_xbrl",
          "unavailable": "Not collected. Filed only as year to date."},
    "obtainable": {"source": "auto", "collector": "sec_xbrl"},
}}


def test_unobtainable_metric_says_so_instead_of_promising_more_periods():
    """`unknown` for a metric no collector can reach must not read as pending.

    The generic wording ("needs at least two periods on record") is true of a
    metric that arrives next quarter and false of one that never arrives. Left
    conflated, the board describes a permanent blind spot as a temporary one and
    goes on doing it for years.
    """
    e = evaluate_one(THRESH, [], {}, REGISTRY)
    assert e.status == "unknown"
    assert "Not collected" in e.detail
    assert "periods on record" not in e.detail


def test_obtainable_metric_keeps_the_ordinary_waiting_message():
    """The override must not swallow the genuine not-enough-history case."""
    rule = dict(THRESH, rule=dict(THRESH["rule"], metric="obtainable"))
    e = evaluate_one(rule, [], {}, REGISTRY)
    assert e.status == "unknown"
    assert "Not collected" not in e.detail


def test_unavailability_never_overrides_a_real_reading():
    """A declared gap is about absence. If a value exists, it wins."""
    hist = [snap("2026-05-01", "m", -900, period="2026Q1"),
            snap("2026-08-01", "m", -900, period="2026Q2")]
    e = evaluate_one(THRESH, hist, {}, REGISTRY)
    assert e.status == "fired"
    assert "Not collected" not in e.detail


def test_registry_omitted_is_backward_compatible():
    """Callers that pass no registry keep the previous behaviour."""
    e = evaluate_one(THRESH, [], {})
    assert e.status == "unknown"
    assert "Not collected" not in e.detail
