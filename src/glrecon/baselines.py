"""Two baselines that need no model. Both return the same CaseExplanation the model will.

naive: looks only at transfer status, so it can only explain NOT_TRANSFERRED items.
rules: applies the design table to every candidate. The bar the model has to match.
"""
from __future__ import annotations

from decimal import Decimal

from . import rules as R
from .db import Candidate, CaseFacts
from .schema import CaseExplanation, EntrySuggestion, ItemExplanation

WHAT_HAPPENED = {
    "NOT_TRANSFERRED": "is in the subledger but was never transferred to the GL",
    "CUTOFF": "is in the subledger this period but its GL journal is in the next period",
    "MANUAL_JE": "is a non-Payables journal posted straight to the AP control account",
    "WRONG_ACCOUNT": "reached the GL in suspense account 2999 instead of 2100",
    "DUPLICATE_JE": "is a second import of a Payables journal that was already posted",
    "REVERSAL_MISSING": "is a prior-period accrual that was due to reverse this period and did not",
    "OPENING_DIFF": "is a difference between subledger and GL opening balances from conversion",
    "ORPHAN_GL_LINE": "is a Payables GL line on 2100 with no subledger source",
}


def money(amount: Decimal) -> str:
    return f"${abs(amount):,.2f}"


def _explain(c: Candidate) -> ItemExplanation:
    rule = R.RULES[c.pattern]
    effect = "GL is short" if c.amount > 0 else "GL is too high"
    accounts = R.entry_accounts(c.pattern, c.amount)
    return ItemExplanation(
        item_id=c.item_id, category=rule.category, side_wrong=rule.side_wrong, owner=rule.owner,
        explanation=f"This {money(c.amount)} item {WHAT_HAPPENED[c.pattern]} ({effect}).",
        action=rule.action,
        correcting_entry=(EntrySuggestion(debit_account=accounts[0], credit_account=accounts[1])
                          if accounts else None),
        prevention=rule.prevention, evidence_ids=list(c.evidence_ids))


def rules(facts: CaseFacts) -> CaseExplanation:
    return CaseExplanation(
        case_id=facts.case_id,
        summary=f"Difference {money(facts.difference)}; every item is explained below.",
        items=[_explain(c) for c in facts.candidates])


def naive(facts: CaseFacts) -> CaseExplanation:
    """Only knows transfer status: blames everything on untransferred entries."""
    items = [ItemExplanation(
        item_id=c.item_id, category="TIMING", side_wrong="NEITHER", owner="AP",
        explanation=f"This {money(c.amount)} entry has not been transferred to the GL.",
        action="Run Transfer to GL.", correcting_entry=None,
        prevention="Check transfer status before close.", evidence_ids=list(c.evidence_ids))
        for c in facts.candidates if c.pattern == "NOT_TRANSFERRED"]
    return CaseExplanation(case_id=facts.case_id,
                           summary="The difference is untransferred subledger entries.",
                           items=items)


BASELINES = {"naive": naive, "rules": rules}
