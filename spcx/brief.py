"""Build the judgment-pass prompt.

Everything a collector cannot fetch — segment tables, categorical states,
unresolved questions — needs a human or a model reading a filing. This renders
the prompt for that pass, seeded from whatever is currently on the record, so it
cannot drift out of sync with the data the way a hand-maintained prompt does.

The disconfirmation section is mandatory and comes first on purpose. A research
loop that only asks "what confirms this" will find confirmation every single
time, and the operator will never notice.
"""

from __future__ import annotations

from .evaluate import evaluate_all
from .models import Snapshot


def render(config: dict, history: list[Snapshot]) -> str:
    evals = evaluate_all(config["criteria"], history, config["manual"], config["metrics"])
    snap = history[-1] if history else Snapshot(run_date="none")

    manual_specs = {m: s for m, s in config["metrics"]["metrics"].items()
                    if s.get("source") == "manual"}
    manual_lines = []
    for metric in manual_specs:
        entry = config["manual"].get("metrics", {}).get(metric)
        if entry:
            manual_lines.append(
                f"- {metric}: {entry['value']} {manual_specs[metric].get('unit','')} "
                f"({entry.get('period','')}, as of {entry['as_of']}, {entry.get('confidence')} confidence)")
        else:
            manual_lines.append(f"- {metric}: NOT ON RECORD")

    auto_lines = [
        f"- {m}: {r.value} {r.unit} (as of {r.as_of}; {r.source})"
        for m, r in sorted(snap.readings.items()) if r.collector != "manual"
    ]

    nearing = [e for e in evals if e.status == "nearing"]
    unknown = [e for e in evals if e.status == "unknown"]
    fired = [e for e in evals if e.status == "fired"]

    unresolved = config["manual"].get("unresolved", [])

    return f"""You are running a judgment pass on SPCX (Space Exploration Technologies Corp,
Nasdaq) for a monitoring system. This is a research instrument, not a trading
account. Write as if you do not know whether the reader is long, short, or flat,
because the system is built so that it does not matter.

Automated collection has already run. Your job is the half that requires reading
filings and exercising judgment.

## 1. DISCONFIRM — do this first, before anything else

Give the strongest evidence found this period AGAINST the long case, then the
strongest evidence AGAINST the short case. Two sections, roughly equal length.
If one side genuinely has nothing new, write "nothing new" rather than padding
it — a forced argument is worse than an admitted gap.

## 2. UPDATE THE MANUAL RECORD

For each value below, find the current figure and give: value, fiscal period,
as-of date, direct source URL, and confidence (high/medium/low). If you cannot
source it, write "unchanged, unverified" — never restate an old number as if it
were freshly confirmed.

Segment figures are tagged with XBRL dimensions the companyfacts API drops, so
they must come from the earnings release segment table directly.

{chr(10).join(manual_lines)}

## 3. EVALUATE

Confirm or correct the mechanical evaluation. A criterion fires only when its
stated condition is literally satisfied — not when it feels close.

Currently fired: {', '.join(e.criterion_id for e in fired) or 'none'}
Currently nearing:
{chr(10).join(f"- {e.criterion_id} {e.label} — {e.detail}" for e in nearing) or '- none'}
Currently unknown (no reading on record — say why, if you can find out):
{chr(10).join(f"- {e.criterion_id} {e.label}" for e in unknown) or '- none'}

## 4. RECORD A FORECAST

Give a calibrated probability for two or three specific, resolvable claims about
the next quarter, each with a resolution date. These get scored later, so state
them precisely enough that resolution is unambiguous. Include your reasoning in
one line each.

## 5. WORK THE BACKLOG

Attempt one unresolved item and report what you found, including failure to
resolve. Say which one you picked.

{chr(10).join(f"- [{u['id']}] {u['text']}" for u in unresolved)}

## AUTOMATED READINGS ALREADY ON RECORD (do not re-fetch, but flag anything implausible)

{chr(10).join(auto_lines) or '- none'}

## EXCLUDED — do not mention regardless of news volume

{chr(10).join(f"- {n}" for n in config['criteria']['not_criteria'])}

## OUTPUT

Lead with any fired criterion. If none fired, the first line is "No criteria
fired" and you do not manufacture significance from a quiet period. Cite a
source URL for every number that changed. Under 900 words.
"""
