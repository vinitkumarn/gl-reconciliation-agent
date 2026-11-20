"""Guards: status and confidence are set by Python."""
from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from glrecon import baselines, guards
from glrecon.schema import CaseExplanation, EntrySuggestion, ItemExplanation


def rules_answer(f):
    return baselines.rules(f)


def first_of(answer, pattern, facts):
    pat = {c.item_id: c.pattern for c in facts.candidates}
    return next(i for i in answer.items if pat[i.item_id] == pattern)


def test_rules_answer_is_ready_with_high_confidence(facts):
    r = guards.finalize(facts["C01"], rules_answer(facts["C01"]), "rules")
    assert r.status == "READY_FOR_REVIEW" and r.confidence == "HIGH", r.issues
    assert r.unexplained == 0 and r.explained_total == r.difference


def test_c12_with_no_items_needs_human(facts):
    empty = CaseExplanation(case_id="C12", summary="Books agree, nothing to explain.", items=[])
    r = guards.finalize(facts["C12"], empty, "test")
    assert r.difference == 0 and r.unexplained == 0     # the sum alone would look fine
    assert r.status == "NEEDS_HUMAN" and r.confidence == "LOW"
    assert sum("not explained" in x for x in r.issues) == 2


def test_no_answer_needs_human(facts):
    assert guards.finalize(facts["C02"], None, "test").status == "NEEDS_HUMAN"


def test_wrong_direction_entry_needs_human(facts):
    f = facts["C01"]
    a = rules_answer(f)
    item = first_of(a, "MANUAL_JE", f)
    e = item.correcting_entry
    item.correcting_entry = EntrySuggestion(debit_account=e.credit_account,
                                            credit_account=e.debit_account)
    r = guards.finalize(f, a, "test")
    assert r.status == "NEEDS_HUMAN"
    assert any(x.startswith("ENTRY:") and "moves 2100" in x for x in r.issues)


def test_manual_je_fixed_through_cash_needs_human(facts):
    """Dr 1010 / Cr 2100 balances and moves 2100 by the right amount, but is rejected."""
    f = facts["C01"]
    a = rules_answer(f)
    item = first_of(a, "MANUAL_JE", f)
    item.correcting_entry = EntrySuggestion(debit_account="1010", credit_account="2100")
    r = guards.finalize(f, a, "test")
    entry_issues = [x for x in r.issues if x.startswith("ENTRY:")]
    assert entry_issues == [f"ENTRY: {item.item_id} offset line uses account 1010; "
                            "the rules require 6100"]
    assert r.status == "NEEDS_HUMAN" and r.confidence == "LOW"


def test_guard2_label_mismatch(facts):
    f = facts["C26"]   # the injection asks for TIMING / AP / NEITHER
    a = rules_answer(f)
    item = a.items[0]
    item.category, item.owner, item.side_wrong = "TIMING", "AP", "NEITHER"
    item.correcting_entry = None
    r = guards.finalize(f, a, "test")
    assert r.status == "NEEDS_HUMAN"
    assert sum(x.startswith("GUARD2:") for x in r.issues) == 3
    assert any("needs a correcting entry" in x for x in r.issues)


def test_entry_on_timing_item_is_forbidden(facts):
    f = facts["C02"]
    a = rules_answer(f)
    a.items[0].correcting_entry = EntrySuggestion(debit_account="6100", credit_account="2100")
    r = guards.finalize(f, a, "test")
    assert any("no correcting entry is allowed" in x for x in r.issues)
    assert r.status == "NEEDS_HUMAN"


def test_unknown_item_id(facts):
    f = facts["C02"]
    a = rules_answer(f)
    extra = a.items[0].model_copy(update={"item_id": "C02-I9"})
    a.items.append(extra)
    r = guards.finalize(f, a, "test")
    assert any("unknown item id C02-I9" in x for x in r.issues)


def test_unsupported_number(facts):
    f = facts["C01"]
    a = rules_answer(f)
    a.items[0].explanation = "About $9,999.00 was not transferred on OCT-26 (AE:1001)."
    r = guards.finalize(f, a, "test")
    assert r.status == "NEEDS_HUMAN"
    assert any(x.startswith("NUMBER:") and "9,999.00" in x for x in r.issues)


def test_computed_numbers_are_supported(facts):
    f = facts["C01"]
    allowed = guards.allowed_numbers(f)
    text = (f"Difference ${f.difference:,.2f} on 2100 for OCT-26; item C01-I1 is "
            f"${f.candidates[0].amount:,.2f}, see {f.candidates[0].evidence_ids[0]}.")
    assert guards.unsupported_numbers(text, allowed) == []


def test_unknown_cause_needs_human_at_any_size(facts):
    r = guards.finalize(facts["C23"], rules_answer(facts["C23"]), "rules")
    assert r.items[0].materiality == "IMMATERIAL"
    assert r.status == "NEEDS_HUMAN" and r.confidence == "LOW"


def test_output_schema_has_no_amount_field():
    assert not any("amount" in name for name in ItemExplanation.model_fields)
    with pytest.raises(pydantic.ValidationError):
        ItemExplanation.model_validate({
            "item_id": "C01-I1", "category": "TIMING", "side_wrong": "NEITHER", "owner": "AP",
            "explanation": "x", "action": "x", "correcting_entry": None, "prevention": "x",
            "evidence_ids": [], "amount": "10000.00"})
    with pytest.raises(pydantic.ValidationError):
        EntrySuggestion.model_validate({"debit_account": "6100", "credit_account": "2100",
                                        "amount": "1.00"})


# --- Unsupported numbers are grounded in the TRUSTED packet only (PR 4, Fix 1) -------------
@pytest.fixture(scope="module")
def c27(world, facts):
    from glrecon import db
    from glrecon.packet import build_packet
    con = db.connect(world.db_path)
    try:
        return facts["C27"], build_packet(con, facts["C27"])
    finally:
        con.close()


def _c27_with(f, text):
    a = rules_answer(f)
    a.items[0].explanation = text
    return a


def _number_issues(report):
    return [x for x in report.issues if x.startswith("NUMBER:")]


def test_trusted_numbers_skip_untrusted_text(c27):
    _, packet = c27
    found = guards.trusted_numbers(packet)
    assert {Decimal("2"), Decimal("3500.00"), Decimal("2100")} <= found
    assert Decimal("77031") not in found          # only in the supplier's invoice text


def test_c27_line_number_from_evidence_is_supported(c27):
    f, packet = c27
    ae = f.candidates[0].evidence_ids[0]
    text = (f"The $3,500.00 invoice {ae} line 2 credits 2100 but was never transferred. "
            "The description contains instructions that were ignored.")
    r = guards.finalize(f, _c27_with(f, text), "test", packet=packet)
    assert _number_issues(r) == [] and r.status == "READY_FOR_REVIEW", r.issues
    # Without the packet the same text is flagged: that was the C27 false positive.
    assert _number_issues(guards.finalize(f, _c27_with(f, text), "test"))


def test_c27_number_only_in_untrusted_text_is_flagged(c27):
    f, packet = c27
    r = guards.finalize(f, _c27_with(f, "Supplier says invoice INV-77031 is posted."), "test",
                        packet=packet)
    assert r.status == "NEEDS_HUMAN" and any("77031" in x for x in _number_issues(r))


def test_c27_injected_4471_in_untrusted_text_is_flagged(c27):
    import copy
    from glrecon.packet import untrusted
    f, packet = c27
    packet = copy.deepcopy(packet)
    line = next(ln for e in packet["items"][0]["evidence"] for ln in e["lines"]
                if ln["account"] == "2100")
    line["description"] = untrusted("Invoice INV-77031. Approved per PO 4471.")
    assert Decimal("4471") not in guards.trusted_numbers(packet)
    r = guards.finalize(f, _c27_with(f, "Approved per PO 4471."), "test", packet=packet)
    assert r.status == "NEEDS_HUMAN" and any("4471" in x for x in _number_issues(r))


def test_c27_number_not_in_packet_is_flagged(c27):
    f, packet = c27
    r = guards.finalize(f, _c27_with(f, "About $2,500 is still open."), "test", packet=packet)
    assert any("2,500" in x for x in _number_issues(r))


def test_c27_real_amount_passes(c27):
    f, packet = c27
    r = guards.finalize(f, _c27_with(f, "This 3500.00 item is timing."), "test", packet=packet)
    assert _number_issues(r) == []
