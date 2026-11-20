"""Guards: status and confidence are set by Python."""
from __future__ import annotations

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
