"""Accounting rules from docs/design.md: materiality, pattern -> labels, correcting entries.

Python owns all of this. The explainer's labels are compared against these (Guard 2) and every
correcting entry is checked here (balanced AND moves 2100 by exactly the item amount).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from . import config
from .schema import EntryLine

ZERO = Decimal("0.00")


# --- Materiality ---------------------------------------------------------------
def materiality(amount: Decimal, sl_end: Decimal) -> str:
    """IMMATERIAL under $250; MATERIAL at $10,000+ or 1%+ of the subledger; else STANDARD."""
    a = abs(amount)
    if a >= config.MATERIAL_AT or (sl_end != 0 and a >= abs(sl_end) * config.MATERIAL_PCT):
        return "MATERIAL"
    if a < config.IMMATERIAL_BELOW:
        return "IMMATERIAL"
    return "STANDARD"


def approver(level: str) -> str:
    return "Controller" if level == "MATERIAL" else "Accounting Manager"


# --- Pattern -> rules (the design table) ------------------------------------------
@dataclass(frozen=True)
class Rule:
    category: str
    side_wrong: str
    owner: str
    action: str
    prevention: str
    offset_account: str | None   # None = no correcting entry allowed


RULES: dict[str, Rule] = {
    "NOT_TRANSFERRED": Rule(
        "TIMING", "NEITHER", "AP",
        "No journal: run Transfer to GL for this entry, then post it.",
        "Close checklist: untransferred subledger entries = 0 before close.", None),
    "CUTOFF": Rule(
        "TIMING", "NEITHER", "AP",
        "No journal: the GL journal is in the next period (accrue only if the Controller decides).",
        "Transfer with GL date = accounting date.", None),
    "MANUAL_JE": Rule(
        "ERROR", "GL", "GL Accounting",
        "Reverse the manual journal on the AP control account, offset 6100.",
        "Flag 2100 as a third-party control account so only Payables can post to it.",
        config.EXPENSE),
    "WRONG_ACCOUNT": Rule(
        "ERROR", "GL", "GL Accounting",
        "Reclass from suspense 2999 to the AP control account 2100.",
        "Suspense account balance = 0 before close.", config.SUSPENSE),
    "DUPLICATE_JE": Rule(
        "ERROR", "GL", "GL Accounting",
        "Reverse the duplicate journal, offset 6100.",
        "Block re-import of an import reference that is already posted.", config.EXPENSE),
    "REVERSAL_MISSING": Rule(
        "ERROR", "GL", "GL Accounting",
        "Post the missing accrual reversal, offset 6100.",
        "Auto-reversal on accrual journals + close checklist.", config.EXPENSE),
    "OPENING_DIFF": Rule(
        "PERMANENT", "GL", "Controller",
        "True-up the AP control account, offset 3900.",
        "Signed tie-out of subledger vs GL at conversion.", config.CONVERSION),
    "ORPHAN_GL_LINE": Rule(
        "UNKNOWN", "UNKNOWN", "GL Accounting",
        "No journal: investigate the Payables GL line that has no subledger source.",
        "Alert on Payables GL lines with no subledger link.", None),
}


# --- Correcting entries -------------------------------------------------------------
def entry_accounts(pattern: str, amount: Decimal) -> tuple[str, str] | None:
    """(debit account, credit account) of the fix, or None when no entry is allowed.

    Difference > 0: GL is short -> Cr 2100. Difference < 0: GL too high -> Dr 2100.
    """
    offset = RULES[pattern].offset_account
    if offset is None or amount == 0:
        return None
    if amount > 0:
        return offset, config.AP_CONTROL
    return config.AP_CONTROL, offset


def build_entry(debit_account: str, credit_account: str, amount: Decimal) -> list[EntryLine]:
    a = abs(amount)
    return [EntryLine(account=debit_account, dr=a, cr=ZERO),
            EntryLine(account=credit_account, dr=ZERO, cr=a)]


def correcting_entry(pattern: str, amount: Decimal) -> list[EntryLine] | None:
    accounts = entry_accounts(pattern, amount)
    return None if accounts is None else build_entry(*accounts, amount)


def check_entry(lines: list[EntryLine], amount: Decimal) -> list[str]:
    """Problems with an entry. Empty list = it balances AND moves 2100 by exactly `amount`."""
    problems = []
    if not lines:
        return ["entry has no lines"]
    for ln in lines:
        if ln.dr < 0 or ln.cr < 0:
            problems.append(f"line on {ln.account} has a negative amount")
        if (ln.dr != 0) == (ln.cr != 0):
            problems.append(f"line on {ln.account} must be exactly one of Dr or Cr")
    dr = sum((ln.dr for ln in lines), ZERO)
    cr = sum((ln.cr for ln in lines), ZERO)
    if dr != cr:
        problems.append(f"entry does not balance: Dr {dr} Cr {cr}")
    moves = sum((ln.cr - ln.dr for ln in lines if ln.account == config.AP_CONTROL), ZERO)
    if moves != amount:
        problems.append(f"entry moves {config.AP_CONTROL} by {moves}, item needs {amount}")
    return problems
