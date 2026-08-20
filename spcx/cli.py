"""Command line interface.

    spcx run          collect, evaluate, write a snapshot, emit latest.json
    spcx evaluate     re-evaluate the existing record without collecting
    spcx check        fail if anything on the manual side has gone stale
    spcx brief        emit the research prompt for a judgment pass
    spcx forecast     add, resolve, and score forecasts
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import collectors, diff, forecast, store
from .evaluate import evaluate_all, summarise
from .models import Snapshot


def _bundle(evals, snap, config) -> dict:
    return {
        "run_date": snap.run_date,
        "generated_at": date.today().isoformat(),
        "criteria_version": config["criteria"]["version"],
        "summary": summarise(evals),
        "evaluations": [e.to_dict() for e in evals],
        "readings": {k: v.to_dict() for k, v in snap.readings.items()},
        "errors": snap.errors,
        "not_criteria": config["criteria"]["not_criteria"],
        "unresolved": config["manual"].get("unresolved", []),
        "calibration": forecast.score(),
    }


def cmd_run(args) -> int:
    config = store.load_config()
    hist = store.history()
    config["history"] = hist

    snap = Snapshot(run_date=args.date or date.today().isoformat())
    collectors.run_all(config, snap, only=args.only)

    evals = evaluate_all(config["criteria"], hist + [snap], config["manual"], config["metrics"])
    summary = summarise(evals)

    path = store.write(snap, force=args.force)
    store.write_latest(_bundle(evals, snap, config))

    # Alert only on a change of status, never on a change of value.
    prev_evals = []
    if hist:
        prev_evals = evaluate_all(config["criteria"], hist, config["manual"], config["metrics"])
        prev_evals = [e.to_dict() for e in prev_evals]
    changed = diff.changes(prev_evals, evals)
    if changed:
        (store.ROOT / "data" / "alert.md").write_text(diff.issue_body(changed, summary), encoding="utf-8")
        print(f"STATUS CHANGE: {', '.join(c['id'] for c in changed)}", file=sys.stderr)

    print(f"snapshot {path.name} · {len(snap.readings)} readings, {len(snap.errors)} gaps")
    print(f"fired {summary['fired'] or '—'} · nearing {summary['nearing'] or '—'} "
          f"· unknown {summary['unknown'] or '—'}")
    if snap.errors:
        for e in snap.errors:
            print(f"  gap: {e['metric']} ({e['collector']}) — {e['reason']}")
    return 1 if changed else 0


def cmd_evaluate(args) -> int:
    config = store.load_config()
    hist = store.history()
    if not hist:
        print("no snapshots on record; run `spcx run` first", file=sys.stderr)
        return 2
    evals = evaluate_all(config["criteria"], hist, config["manual"], config["metrics"])
    for e in sorted(evals, key=lambda x: (x.case, x.tier, x.criterion_id)):
        mark = {"fired": "!!", "nearing": " ~", "unknown": " ?", "clear": "  "}[e.status]
        print(f"{mark} {e.criterion_id:<4} {e.status:<8} {e.label[:52]:<54} {e.detail}")
    print()
    print(json.dumps(summarise(evals), indent=2))
    return 0


def cmd_check(args) -> int:
    """Fail the build when the judgment half has aged out.

    A monitoring system whose manual inputs silently rot is worse than none:
    it displays confident green while describing a world six months old.
    """
    config = store.load_config()
    limits = {"quarterly": 100, "biweekly": 21, "event": 400, "daily": 5}
    specs = config["metrics"]["metrics"]
    stale = []
    for metric, entry in config["manual"].get("metrics", {}).items():
        cadence = specs.get(metric, {}).get("cadence", "quarterly")
        age = (date.today() - date.fromisoformat(str(entry["as_of"]))).days
        if age > limits.get(cadence, 100):
            stale.append((metric, age, limits.get(cadence, 100)))
    for key, entry in config["manual"].get("states", {}).items():
        age = (date.today() - date.fromisoformat(str(entry["as_of"]))).days
        if age > 120:
            stale.append((key, age, 120))

    od = forecast.overdue()
    for f in od:
        print(f"overdue forecast {f['id']}: {f['statement'][:70]} (due {f['resolve_by']})")
    for metric, age, limit in stale:
        print(f"stale: {metric} is {age}d old, limit {limit}d")

    if stale or od:
        print(f"\n{len(stale)} stale input(s), {len(od)} overdue forecast(s). "
              f"Run a judgment pass: `spcx brief`.")
        return 1
    print("manual inputs current, no overdue forecasts")
    return 0


def cmd_brief(args) -> int:
    from .brief import render
    print(render(store.load_config(), store.history()))
    return 0


def cmd_forecast(args) -> int:
    if args.action == "add":
        e = forecast.add(args.statement, args.probability, args.resolve_by,
                         criterion=args.criterion, basis=args.basis or "")
        print(f"{e['id']}: {e['probability']:.0%} — {e['statement']}")
    elif args.action == "resolve":
        e = forecast.resolve(args.id, args.outcome == "true", note=args.note or "")
        print(f"{e['id']} resolved {e['outcome']}")
    elif args.action == "score":
        s = forecast.score()
        if not s["n"]:
            print("no resolved forecasts yet")
            return 0
        print(json.dumps(s, indent=2))
        if not s["beats_base_rate"]:
            print("\nThese forecasts are not beating the base rate. That is a "
                  "finding about the process, not a rounding error.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="spcx", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="collect and evaluate")
    r.add_argument("--date", help="override run date (ISO)")
    r.add_argument("--force", action="store_true", help="overwrite an existing snapshot")
    r.add_argument("--only", nargs="*", help="run only these collectors")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("evaluate", help="re-evaluate without collecting")
    e.set_defaults(fn=cmd_evaluate)

    c = sub.add_parser("check", help="fail if manual inputs are stale")
    c.set_defaults(fn=cmd_check)

    b = sub.add_parser("brief", help="print the judgment-pass prompt")
    b.set_defaults(fn=cmd_brief)

    f = sub.add_parser("forecast", help="add, resolve, or score forecasts")
    fs = f.add_subparsers(dest="action", required=True)
    fa = fs.add_parser("add")
    fa.add_argument("statement")
    fa.add_argument("probability", type=float)
    fa.add_argument("resolve_by")
    fa.add_argument("--criterion")
    fa.add_argument("--basis")
    fr = fs.add_parser("resolve")
    fr.add_argument("id")
    fr.add_argument("outcome", choices=["true", "false"])
    fr.add_argument("--note")
    fs.add_parser("score")
    f.set_defaults(fn=cmd_forecast)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
