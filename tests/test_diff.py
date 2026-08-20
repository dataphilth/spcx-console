import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spcx import diff
from spcx.models import Evaluation


def ev(i, status, case="long", tier=1):
    return Evaluation(criterion_id=i, case=case, tier=tier, label=f"{i} label",
                      status=status, value=1, threshold=0, unit="$M",
                      proximity=None, streak=0, required=1, detail="d")


def test_only_status_changes_alert():
    prev = [ev("L1", "clear").to_dict(), ev("L2", "nearing").to_dict()]
    curr = [ev("L1", "clear"), ev("L2", "nearing")]
    assert diff.changes(prev, curr) == []


def test_escalation_and_deescalation_both_reported():
    prev = [ev("L1", "clear").to_dict(), ev("L2", "fired").to_dict()]
    curr = [ev("L1", "fired"), ev("L2", "nearing")]
    out = diff.changes(prev, curr)
    assert {c["id"]: c["direction"] for c in out} == {
        "L1": "escalation", "L2": "de-escalation"}


def test_fired_sorts_first():
    prev = [ev("L1", "clear").to_dict(), ev("L2", "clear").to_dict()]
    curr = [ev("L1", "nearing"), ev("L2", "fired")]
    assert diff.changes(prev, curr)[0]["id"] == "L2"


def test_new_criterion_does_not_alert():
    """Adding a criterion to the yaml should not page you at 3am."""
    assert diff.changes([], [ev("L9", "fired")]) == []
