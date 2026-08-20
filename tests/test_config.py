"""The config files are the product. If they drift from the code, nothing works."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from spcx import store
from spcx.evaluate import OPS


@pytest.fixture(scope="module")
def config():
    return store.load_config()


def test_every_criterion_id_is_unique(config):
    ids = [c["id"] for c in config["criteria"]["criteria"]]
    assert len(ids) == len(set(ids))


def test_every_rule_references_a_declared_metric_or_state(config):
    metrics = set(config["metrics"]["metrics"])
    states = set(config["manual"].get("states", {}))
    for c in config["criteria"]["criteria"]:
        r = c["rule"]
        if r["type"] in ("threshold", "streak"):
            assert r["metric"] in metrics, f"{c['id']} references unknown metric {r['metric']}"
        elif r["type"] == "compare":
            assert r["metric"] in metrics and r["against"] in metrics, c["id"]
        elif r["type"] == "manual":
            assert r["key"] in states, f"{c['id']} references unknown state {r['key']}"


def test_operators_are_implemented(config):
    for c in config["criteria"]["criteria"]:
        op = c["rule"].get("operator")
        if op:
            assert op in OPS, f"{c['id']} uses unimplemented operator {op}"


def test_both_cases_are_represented(config):
    """Structural guard against the board drifting into a bull dashboard."""
    cases = [c["case"] for c in config["criteria"]["criteria"]]
    assert cases.count("long") >= 5 and cases.count("short") >= 5


def test_manual_metrics_are_declared_manual(config):
    specs = config["metrics"]["metrics"]
    for metric in config["manual"].get("metrics", {}):
        assert specs[metric]["source"] == "manual", f"{metric} is filled by hand but marked auto"


def test_scales_bracket_their_thresholds(config):
    for c in config["criteria"]["criteria"]:
        scale, rule = c.get("scale"), c["rule"]
        if scale and rule["type"] == "threshold":
            lo, hi = min(scale), max(scale)
            assert lo <= rule["threshold"] <= hi, f"{c['id']} threshold outside its display scale"
