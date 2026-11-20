"""Pydantic models: what the explainer may return (NO amounts) and the final report."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Category = Literal["TIMING", "ERROR", "PERMANENT", "UNKNOWN"]
Side = Literal["NEITHER", "GL", "SUBLEDGER", "UNKNOWN"]
Owner = Literal["AP", "GL Accounting", "Controller"]
Materiality = Literal["IMMATERIAL", "STANDARD", "MATERIAL"]
Status = Literal["READY_FOR_REVIEW", "NEEDS_HUMAN"]
Confidence = Literal["HIGH", "LOW"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- What the explainer returns. There is deliberately no amount field anywhere. ------
class EntrySuggestion(Strict):
    """Which account to debit and which to credit. Python attaches the amount."""
    debit_account: str
    credit_account: str


class ItemExplanation(Strict):
    item_id: str
    category: Category
    side_wrong: Side
    owner: Owner
    explanation: str
    action: str
    correcting_entry: EntrySuggestion | None
    prevention: str
    evidence_ids: list[str]


class CaseExplanation(Strict):
    case_id: str
    summary: str
    items: list[ItemExplanation]


# --- The final report. Every number here comes from Python. --------------------------
class EntryLine(Strict):
    account: str
    dr: Decimal
    cr: Decimal


class ReportItem(Strict):
    item_id: str
    pattern: str
    amount: Decimal
    materiality: Materiality
    approver: str
    evidence_ids: list[str]
    explained: bool
    category: Category | None = None
    side_wrong: Side | None = None
    owner: Owner | None = None
    explanation: str = ""
    action: str = ""
    prevention: str = ""
    correcting_entry: list[EntryLine] | None = None
    issues: list[str] = []


class CaseReport(Strict):
    case_id: str
    by: str
    period: str
    sl_end: Decimal
    gl_end: Decimal
    difference: Decimal
    explained_total: Decimal
    unexplained: Decimal
    status: Status
    confidence: Confidence
    summary: str = ""
    issues: list[str]
    items: list[ReportItem]
    latency_ms: int = 0
