"""Materiality edges and correcting entries."""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from glrecon import rules
from glrecon.schema import EntryLine

BIG_SL = D("2000000.00")   # 1% = 20,000, so only the dollar thresholds matter


@pytest.mark.parametrize("amount, level", [
    ("249.99", "IMMATERIAL"), ("-249.99", "IMMATERIAL"),
    ("250.00", "STANDARD"), ("9999.99", "STANDARD"),
    ("10000.00", "MATERIAL"), ("-10000.00", "MATERIAL"),
])
def test_materiality_dollar_edges(amount, level):
    assert rules.materiality(D(amount), BIG_SL) == level


def test_materiality_exactly_one_percent():
    sl = D("481250.00")
    assert rules.materiality(D("4812.50"), sl) == "MATERIAL"
    assert rules.materiality(D("4812.49"), sl) == "STANDARD"


def test_approver():
    assert rules.approver("MATERIAL") == "Controller"
    assert rules.approver("STANDARD") == "Accounting Manager"
    assert rules.approver("IMMATERIAL") == "Accounting Manager"


@pytest.mark.parametrize("pattern", [p for p, r in rules.RULES.items() if r.offset_account])
@pytest.mark.parametrize("amount", ["2400.00", "-6045.20"])
def test_error_and_permanent_entries_balance_and_fix_exact_amount(pattern, amount):
    lines = rules.correcting_entry(pattern, D(amount))
    assert lines and rules.check_entry(lines, D(amount)) == []


def test_timing_and_unknown_get_no_entry():
    for p in ("NOT_TRANSFERRED", "CUTOFF", "ORPHAN_GL_LINE"):
        assert rules.correcting_entry(p, D("100.00")) is None


def test_design_entries():
    # WRONG_ACCOUNT: Dr 2999 / Cr 2100
    assert rules.entry_accounts("WRONG_ACCOUNT", D("3318.75")) == ("2999", "2100")
    # GL too high -> Dr 2100
    assert rules.entry_accounts("DUPLICATE_JE", D("-6045.20")) == ("2100", "6100")
    assert rules.entry_accounts("OPENING_DIFF", D("-1904.33")) == ("2100", "3900")


def test_wrong_direction_entry_fails():
    flipped = rules.build_entry("2100", "6100", D("2400.00"))   # should be Dr 6100 / Cr 2100
    problems = rules.check_entry(flipped, D("2400.00"))
    assert any("moves 2100" in p for p in problems)


def test_unbalanced_entry_fails():
    lines = [EntryLine(account="6100", dr=D("2400.00"), cr=D("0")),
             EntryLine(account="2100", dr=D("0"), cr=D("2399.99"))]
    problems = rules.check_entry(lines, D("2399.99"))
    assert any("does not balance" in p for p in problems)


def test_entry_not_touching_2100_fails():
    lines = rules.build_entry("6100", "2999", D("500.00"))
    assert rules.check_entry(lines, D("500.00"))
