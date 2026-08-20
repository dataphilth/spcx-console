"""Detect status changes between runs.

The alerting rule is deliberately narrow: notify on a *change of status*, never
on a change of value. A metric that moves every day would otherwise train the
operator to ignore the channel, which is the failure mode that makes monitoring
systems useless six months in.
"""

from __future__ import annotations

from typing import Any

from .models import Evaluation

RANK = {"clear": 0, "unknown": 1, "nearing": 2, "fired": 3}


def changes(prev: list[dict], curr: list[Evaluation]) -> list[dict[str, Any]]:
    before = {e["criterion_id"]: e for e in prev}
    out = []
    for e in curr:
        old = before.get(e.criterion_id)
        if old is None:
            continue
        if old["status"] != e.status:
            out.append({
                "id": e.criterion_id, "label": e.label, "case": e.case, "tier": e.tier,
                "from": old["status"], "to": e.status, "detail": e.detail,
                "direction": "escalation" if RANK[e.status] > RANK[old["status"]] else "de-escalation",
            })
    out.sort(key=lambda c: (-RANK[c["to"]], c["tier"]))
    return out


def issue_body(changes_: list[dict], summary: dict) -> str:
    """Markdown for a GitHub issue. Only written when something actually changed."""
    lines = ["## Criterion status change", ""]
    for c in changes_:
        arrow = "▲" if c["direction"] == "escalation" else "▼"
        lines.append(f"**{arrow} {c['id']} · {c['label']}**  ")
        lines.append(f"`{c['from']}` → `{c['to']}` · tier {c['tier']} · breaks the {c['case']} case  ")
        lines.append(f"{c['detail']}")
        lines.append("")
    lines += [
        "---", "",
        f"Fired: {', '.join(summary['fired']) or 'none'}  ",
        f"Nearing: {', '.join(summary['nearing']) or 'none'}  ",
        f"Unknown: {', '.join(summary['unknown']) or 'none'}  ",
        "",
        "A status change is not an instruction. Read the criterion, check the "
        "source, and record a forecast before deciding anything.",
    ]
    return "\n".join(lines)
