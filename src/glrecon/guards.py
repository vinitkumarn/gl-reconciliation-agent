"""Guards: turn facts + an explanation into the final report. Status and confidence are set HERE.

Guard 1  candidates add up to the difference exactly, and every candidate is explained.
Guard 2  category / wrong side / owner agree with the rules.
Entries  required for ERROR/PERMANENT, forbidden otherwise, balanced, move 2100 by the item amount,
         and the other line uses the rules' offset account (6100 / 2999 / 3900).
Numbers  every number in the text is a number Python computed, or appears in a TRUSTED part of
         the facts packet (amounts, balances, accounts, ids, line numbers, dates). Numbers that
         appear only inside <UNTRUSTED> text are not supported: supplier text is not a source.
Any issue -> NEEDS_HUMAN with LOW confidence. An UNKNOWN cause -> NEEDS_HUMAN at any size.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from . import config, rules
from .db import CaseFacts
from .schema import CaseExplanation, CaseReport, ReportItem

ZERO = Decimal("0.00")

# Tokens that contain digits but are ids, not amounts. Removed before the number check.
_ID_TOKENS = re.compile(
    r"\b(?:AE|JE|BAL):[A-Za-z0-9]+"     # evidence ids
    r"|\bC\d{2}-I\d+\b"                 # item ids
    r"|\bC\d{2}\b"                      # case ids
    r"|\b[A-Z]{3}-\d{2}\b")             # period names like OCT-26
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def allowed_numbers(facts: CaseFacts) -> set[Decimal]:
    """Every number the text may quote: computed by Python or fixed in config."""
    values = {facts.sl_end, facts.gl_end, facts.difference, ZERO,
              config.IMMATERIAL_BELOW, config.MATERIAL_AT, config.MATERIAL_PCT * 100}
    running = ZERO
    for c in facts.candidates:
        values.add(c.amount)
        running += c.amount
        values.add(running)
        for e in c.evidence_ids:
            tail = e.split(":", 1)[1]
            if tail.isdigit():
                values.add(Decimal(tail))
    values |= {Decimal(a) for a in config.ACCOUNTS}
    return {abs(v) for v in values}


def trusted_numbers(packet) -> set[Decimal]:
    """Every number in the packet outside <UNTRUSTED> text, compared as numbers."""
    found: set[Decimal] = set()
    if isinstance(packet, dict):
        for value in packet.values():
            found |= trusted_numbers(value)
    elif isinstance(packet, list):
        for value in packet:
            found |= trusted_numbers(value)
    elif packet is None or isinstance(packet, bool):   # bool before int: True is not 1 here
        pass
    elif isinstance(packet, str) and packet.startswith("<UNTRUSTED>"):
        pass
    else:
        for raw in _NUMBER.findall(str(packet)):
            found.add(abs(Decimal(raw.replace(",", ""))))
    return found


def unsupported_numbers(text: str, allowed: set[Decimal]) -> list[str]:
    bad = []
    for raw in _NUMBER.findall(_ID_TOKENS.sub(" ", text)):
        try:
            value = Decimal(raw.replace(",", "").rstrip("."))
        except InvalidOperation:
            bad.append(raw)
            continue
        if value not in allowed:
            bad.append(raw)
    return bad


def finalize(facts: CaseFacts, answer: CaseExplanation | None, by: str,
             latency_ms: int = 0, packet: dict | None = None) -> CaseReport:
    issues: list[str] = []
    allowed = allowed_numbers(facts)
    if packet is not None:
        allowed |= trusted_numbers(packet)
    by_item = {c.item_id: c for c in facts.candidates}

    # --- Guard 1a: candidates must add up to the difference exactly -----------------------
    candidate_total = sum((c.amount for c in facts.candidates), ZERO)
    if candidate_total != facts.difference:
        issues.append(f"GUARD1: candidates add up to {candidate_total}, "
                      f"difference is {facts.difference}")

    explanations = {}
    if answer is None:
        issues.append("GUARD1: no valid explanation")
    else:
        if answer.case_id != facts.case_id:
            issues.append(f"GUARD1: explanation is for case {answer.case_id}")
        for x in answer.items:
            if x.item_id not in by_item:
                issues.append(f"GUARD1: unknown item id {x.item_id}")
            elif x.item_id in explanations:
                issues.append(f"GUARD1: item {x.item_id} explained twice")
            else:
                explanations[x.item_id] = x
        bad = unsupported_numbers(answer.summary, allowed)
        if bad:
            issues.append(f"NUMBER: unsupported number(s) in summary: {', '.join(bad)}")

    items: list[ReportItem] = []
    explained_total = ZERO
    for c in facts.candidates:
        rule = rules.RULES[c.pattern]
        level = rules.materiality(c.amount, facts.sl_end)
        item = ReportItem(item_id=c.item_id, pattern=c.pattern, amount=c.amount,
                          materiality=level, approver=rules.approver(level),
                          evidence_ids=list(c.evidence_ids), explained=False)
        x = explanations.get(c.item_id)
        if x is None:
            # --- Guard 1b: every candidate must be explained ---
            item.issues.append(f"GUARD1: item {c.item_id} ({c.pattern} {c.amount}) not explained")
        else:
            item.explained = True
            explained_total += c.amount
            item.category, item.side_wrong, item.owner = x.category, x.side_wrong, x.owner
            item.explanation, item.action, item.prevention = x.explanation, x.action, x.prevention

            # --- Guard 2: labels must agree with the rules ---
            for field, want in (("category", rule.category), ("side_wrong", rule.side_wrong),
                                ("owner", rule.owner)):
                got = getattr(x, field)
                if got != want:
                    item.issues.append(f"GUARD2: {c.item_id} {field} is {got}, rules say {want}")

            # --- Entry rules (by the rules' category, not the explainer's) ---
            needs_entry = rule.category in ("ERROR", "PERMANENT")
            if x.correcting_entry is None:
                if needs_entry:
                    item.issues.append(f"ENTRY: {c.item_id} is {rule.category} "
                                       "and needs a correcting entry")
            elif not needs_entry:
                item.issues.append(f"ENTRY: {c.item_id} is {rule.category}; "
                                   "no correcting entry is allowed")
            else:
                lines = rules.build_entry(x.correcting_entry.debit_account,
                                          x.correcting_entry.credit_account, c.amount)
                item.correcting_entry = lines
                item.issues += [f"ENTRY: {c.item_id} {p}" for p in rules.check_entry(
                    lines, c.amount, rule.offset_account)]

            # --- Unsupported numbers ---
            for field in ("explanation", "action", "prevention"):
                bad = unsupported_numbers(getattr(x, field), allowed)
                if bad:
                    item.issues.append(f"NUMBER: {c.item_id} {field} has unsupported "
                                       f"number(s): {', '.join(bad)}")
        if rule.category == "UNKNOWN":
            item.issues.append(f"UNKNOWN: {c.item_id} cause is unknown; a human must investigate")
        items.append(item)
        issues += item.issues

    unexplained = facts.difference - explained_total
    if unexplained != 0:
        issues.append(f"GUARD1: {unexplained} of the difference is unexplained")

    status = "NEEDS_HUMAN" if issues else "READY_FOR_REVIEW"
    return CaseReport(
        case_id=facts.case_id, by=by, period=facts.period, sl_end=facts.sl_end,
        gl_end=facts.gl_end, difference=facts.difference, explained_total=explained_total,
        unexplained=unexplained, status=status,
        confidence="LOW" if status == "NEEDS_HUMAN" else "HIGH",
        summary=answer.summary if answer else "", issues=issues, items=items,
        latency_ms=latency_ms)
