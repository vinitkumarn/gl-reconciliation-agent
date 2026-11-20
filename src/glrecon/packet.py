"""Build the ONE JSON facts packet the model sees for a case.

Every number in it comes from SQL/Python. Supplier ids are replaced by masked labels
(SUPPLIER_A, SUPPLIER_B, ...) and supplier names are never read. Every free-text description
is wrapped as <UNTRUSTED>...</UNTRUSTED> with &, < and > escaped, so text in the data cannot
close the tag or pose as an instruction.
"""
from __future__ import annotations

import hashlib
import json
import string
from decimal import Decimal

from . import config, rules
from .db import CaseFacts, evidence_rows


def untrusted(text: str | None) -> str:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<UNTRUSTED>{safe}</UNTRUSTED>"


def _money(value) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


class _Masker:
    """Same supplier id -> same label within one packet; order of first appearance."""

    def __init__(self) -> None:
        self.labels: dict[int, str] = {}

    def __call__(self, supplier_id) -> str | None:
        if supplier_id is None:
            return None
        if supplier_id not in self.labels:
            self.labels[supplier_id] = f"SUPPLIER_{string.ascii_uppercase[len(self.labels)]}"
        return self.labels[supplier_id]


def _evidence(con, case_id: str, evidence_id: str, mask: _Masker) -> dict:
    raw = evidence_rows(con, case_id, evidence_id)
    h = raw["header"]
    if raw["kind"] == "AE":
        return {
            "evidence_id": evidence_id, "source": "AP subledger entry",
            "accounting_date": str(h["accounting_date"]), "period": h["period_name"],
            "transferred_to_gl": h["gl_transfer_status_code"] == "Y",
            "supplier": mask(h["supplier_id"]),
            "lines": [{"line": ln["ae_line_num"], "account": ln["account"],
                       "accounting_class": ln["accounting_class"],
                       "dr": _money(ln["accounted_dr"]), "cr": _money(ln["accounted_cr"]),
                       "linked_to_gl": ln["gl_sl_link_id"] is not None,
                       "description": untrusted(ln["description"])}
                      for ln in raw["lines"]]}
    if raw["kind"] == "JE":
        return {
            "evidence_id": evidence_id, "source": "GL journal",
            "je_source": h["je_source"], "period": h["period_name"],
            "posted": h["status"] == "P", "import_ref": h["import_ref"],
            "accrual_reverse_in_period": h["accrual_rev_period"],
            "accrual_reversed": (None if h["accrual_rev_status"] is None
                                 else h["accrual_rev_status"] == "Y"),
            "description": untrusted(h["description"]),
            "lines": [{"line": ln["je_line_num"], "account": ln["account"],
                       "dr": _money(ln["accounted_dr"]), "cr": _money(ln["accounted_cr"]),
                       "linked_to_subledger": ln["gl_sl_link_id"] is not None}
                      for ln in raw["lines"]]}
    return {"evidence_id": evidence_id, "source": "opening balances",
            "period": h["period_name"],
            "subledger_opening_liability": _money(h["subledger_opening"]),
            "gl_opening_liability": _money(h["gl_opening"])}


def build_packet(con, facts: CaseFacts) -> dict:
    mask = _Masker()
    items = []
    for c in facts.candidates:
        level = rules.materiality(c.amount, facts.sl_end)
        items.append({
            "item_id": c.item_id, "pattern": c.pattern, "amount": _money(c.amount),
            "effect": "GL is short" if c.amount > 0 else "GL is too high",
            "materiality": level, "approver": rules.approver(level),
            "evidence_ids": list(c.evidence_ids),
            "evidence": [_evidence(con, facts.case_id, e, mask) for e in c.evidence_ids]})
    return {
        "case_id": facts.case_id, "period": facts.period,
        "control_account": config.AP_CONTROL, "currency": "USD",
        "sign_rule": "liability = Cr - Dr; difference = subledger - GL",
        "subledger_balance": _money(facts.sl_end), "gl_balance": _money(facts.gl_end),
        "difference": _money(facts.difference),
        "items_total": _money(sum((c.amount for c in facts.candidates), Decimal("0.00"))),
        "items": items}


def packet_json(packet: dict) -> str:
    """Canonical text of the packet: sorted keys, no extra spaces. Same facts -> same bytes."""
    return json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
