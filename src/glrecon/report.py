"""Render one CaseReport as Markdown."""
from __future__ import annotations

from decimal import Decimal

from .schema import CaseReport


def money(amount: Decimal) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def render(r: CaseReport) -> str:
    out = [
        f"# Reconciliation {r.case_id} — AP control 2100, {r.period} (by {r.by})",
        "",
        "_Suggestion only. A human approves. Nothing is posted._",
        "",
        "| | Amount |", "|---|---:|",
        f"| Subledger balance | {money(r.sl_end)} |",
        f"| GL balance | {money(r.gl_end)} |",
        f"| Difference (Subledger - GL) | {money(r.difference)} |",
        f"| Explained | {money(r.explained_total)} |",
        f"| Unexplained | {money(r.unexplained)} |",
        "",
        f"**Status:** {r.status}  **Confidence:** {r.confidence}",
        "",
    ]
    if r.summary:
        out += [f"Summary: {r.summary}", ""]
    if r.items:
        out += ["## Items", "",
                "| Item | Pattern | Amount | Materiality | Approver | Category | Wrong side | Owner |",
                "|---|---|---:|---|---|---|---|---|"]
        for i in r.items:
            out.append(f"| {i.item_id} | {i.pattern} | {money(i.amount)} | {i.materiality} | "
                       f"{i.approver} | {i.category or '-'} | {i.side_wrong or '-'} | "
                       f"{i.owner or '-'} |")
        for i in r.items:
            out += ["", f"### {i.item_id} {i.pattern} {money(i.amount)}",
                    f"- Evidence: {', '.join(i.evidence_ids)}"]
            if not i.explained:
                out.append("- **Not explained.**")
            else:
                out += [f"- Explanation: {i.explanation}", f"- Action: {i.action}",
                        f"- Prevention: {i.prevention}"]
                if i.correcting_entry:
                    out.append("- Suggested correcting entry (not posted):")
                    for ln in i.correcting_entry:
                        side = f"Dr {money(ln.dr)}" if ln.dr else f"Cr {money(ln.cr)}"
                        out.append(f"  - {ln.account} {side}")
                else:
                    out.append("- Correcting entry: none")
    else:
        out.append("No reconciling items.")
    if r.issues:
        out += ["", "## Issues (why a human must look)", ""] + [f"- {x}" for x in r.issues]
    return "\n".join(out) + "\n"
