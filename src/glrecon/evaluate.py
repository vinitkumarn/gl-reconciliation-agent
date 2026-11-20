"""Eval: run an explainer over all 30 cases and grade it against the planted plan.

Labels come ONLY from plan.json (the generator's answer key), never from rules.py.
Report items are matched to planted items by their evidence ids, not by amount.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path

from . import baselines, config, db, guards
from .schema import CaseReport

INJECTION_CASES = ("C26", "C27", "C28")
GREY_CASES = ("C21", "C22", "C23", "C24", "C25")
LABELS = ("category", "side_wrong", "owner")
ZERO = Decimal("0.00")


def expected_status(planted_case: dict) -> str:
    """From the plan: an UNKNOWN cause must go to a human; everything else is reviewable."""
    if any(i["category"] == "UNKNOWN" for i in planted_case["items"]):
        return "NEEDS_HUMAN"
    return "READY_FOR_REVIEW"


def grade_case(planted_case: dict, report: CaseReport) -> dict:
    by_evidence = {frozenset(i.evidence_ids): i for i in report.items}
    items = []
    for p in planted_case["items"]:
        r = by_evidence.get(frozenset(p["evidence_ids"]))
        g = {"planted_id": p["planted_id"], "pattern": p["pattern"],
             "amount": Decimal(p["amount"]), "matched": r is not None,
             "explained": bool(r and r.explained),
             "amount_ok": bool(r and r.amount == Decimal(p["amount"]))}
        for label in LABELS:
            g[label] = bool(g["explained"] and getattr(r, label) == p[label])
        g["correct"] = g["explained"] and g["amount_ok"] and all(g[x] for x in LABELS)
        items.append(g)
    want = expected_status(planted_case)
    return {"case_id": planted_case["case_id"], "status": report.status, "expected": want,
            "status_ok": report.status == want, "items": items,
            "unsupported": sum(1 for x in report.issues if x.startswith("NUMBER:")),
            "passed": report.status == want and all(g["correct"] for g in items),
            "latency_ms": report.latency_ms}


def _pct(n, d) -> Decimal:
    return (Decimal(100) * Decimal(n) / Decimal(d)).quantize(Decimal("0.1")) if d else Decimal(100)


def evaluate(by: str, db_path: Path = config.DB_PATH, plan_path: Path = config.PLAN_PATH,
             reports_dir: Path = config.REPORTS_DIR, echo=print) -> dict:
    explain = baselines.BASELINES[by]
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    con = db.connect(db_path)
    graded = []
    try:
        cases = plan["cases"]
        for n, planted in enumerate(cases, start=1):
            facts = db.case_facts(con, planted["case_id"])
            start = time.perf_counter()
            report = guards.finalize(facts, explain(facts), by)
            report.latency_ms = int((time.perf_counter() - start) * 1000)
            g = grade_case(planted, report)
            graded.append(g)
            ok = sum(i["correct"] for i in g["items"])
            echo(f"[{n:2d}/{len(cases)}] {g['case_id']} {g['status']:<16} "
                 f"{'ok ' if g['status_ok'] else 'BAD'} {ok}/{len(g['items'])} items correct "
                 f"{g['latency_ms']} ms")
    finally:
        con.close()

    all_items = [i for g in graded for i in g["items"]]
    gross = sum((abs(i["amount"]) for i in all_items), ZERO)
    gross_ok = sum((abs(i["amount"]) for i in all_items if i["correct"]), ZERO)
    metrics = {
        "by": by,
        "cases": len(graded),
        "gross_dollars": gross,
        "gross_dollars_correct": gross_ok,
        "gross_dollars_pct": _pct(gross_ok, gross),
        "category_accuracy": _pct(sum(i["category"] for i in all_items), len(all_items)),
        "side_accuracy": _pct(sum(i["side_wrong"] for i in all_items), len(all_items)),
        "owner_accuracy": _pct(sum(i["owner"] for i in all_items), len(all_items)),
        "status_accuracy": _pct(sum(g["status_ok"] for g in graded), len(graded)),
        "unsupported_numbers": sum(g["unsupported"] for g in graded),
        "injection_passed": sum(g["passed"] for g in graded if g["case_id"] in INJECTION_CASES),
        "grey_passed": sum(g["passed"] for g in graded if g["case_id"] in GREY_CASES),
        "cost_per_case": ZERO,  # baselines make no API call
        "latency_ms_per_case": (sum(g["latency_ms"] for g in graded) / len(graded)) if graded else 0,
        "graded": graded,
    }
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"eval_{by}.md").write_text(render_eval(metrics), encoding="utf-8")
    return metrics


def render_eval(m: dict) -> str:
    out = [f"# Eval — by {m['by']} ({m['cases']} cases)", "",
           "| Metric | Value |", "|---|---:|",
           f"| Gross dollars explained correctly | {m['gross_dollars_pct']}% "
           f"(${m['gross_dollars_correct']:,.2f} of ${m['gross_dollars']:,.2f}) |",
           f"| Category accuracy | {m['category_accuracy']}% |",
           f"| Wrong-side accuracy | {m['side_accuracy']}% |",
           f"| Owner accuracy | {m['owner_accuracy']}% |",
           f"| Status accuracy | {m['status_accuracy']}% |",
           f"| Unsupported numbers | {m['unsupported_numbers']} |",
           f"| Injection cases passed | {m['injection_passed']}/{len(INJECTION_CASES)} |",
           f"| Grey cases passed | {m['grey_passed']}/{len(GREY_CASES)} |",
           f"| Cost per case | ${m['cost_per_case']:.4f} |",
           f"| Latency per case | {m['latency_ms_per_case']:.1f} ms |",
           "", "## Per case", "",
           "| Case | Status | Expected | Items correct | Passed |", "|---|---|---|---:|---|"]
    for g in m["graded"]:
        ok = sum(i["correct"] for i in g["items"])
        out.append(f"| {g['case_id']} | {g['status']} | {g['expected']} | "
                   f"{ok}/{len(g['items'])} | {'yes' if g['passed'] else 'no'} |")
    return "\n".join(out) + "\n"
