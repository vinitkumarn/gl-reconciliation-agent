"""All fixed settings in one place: accounts, periods, materiality, paths, model."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CSV_DIR = DATA_DIR / "csv"
PLAN_PATH = DATA_DIR / "plan.json"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "glrecon.duckdb"
SQL_DIR = ROOT / "sql"

# --- Accounts --------------------------------------------------------------
AP_CONTROL = "2100"   # AP liability control account (the account we reconcile)
SUSPENSE = "2999"     # suspense / wrong account
EXPENSE = "6100"      # expense, default offset for corrections
CASH = "1010"         # cash
CONVERSION = "3900"   # conversion / opening balance equity
ACCOUNTS = (AP_CONTROL, SUSPENSE, EXPENSE, CASH, CONVERSION)

# --- Periods ---------------------------------------------------------------
PRIOR_PERIOD = "SEP-26"
RECON_PERIOD = "OCT-26"
NEXT_PERIOD = "NOV-26"
# period_name -> (status, start_date, end_date). C = closed, O = open.
PERIODS = {
    PRIOR_PERIOD: ("C", "2026-09-01", "2026-09-30"),
    RECON_PERIOD: ("O", "2026-10-01", "2026-10-31"),
    NEXT_PERIOD: ("O", "2026-11-01", "2026-11-30"),
}

# --- Materiality (the Controller owns these numbers) -------------------------
IMMATERIAL_BELOW = Decimal("250.00")   # under this -> IMMATERIAL
MATERIAL_AT = Decimal("10000.00")      # this or more -> MATERIAL
MATERIAL_PCT = Decimal("0.01")         # or 1% or more of the subledger balance -> MATERIAL

# --- Synthetic data ----------------------------------------------------------
SEED = 20261031


# --- Model -------------------------------------------------------------------
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # config must work even before dependencies are installed
        return
    load_dotenv(ROOT / ".env")


_load_dotenv()
MODEL = os.environ.get("GLRECON_MODEL") or "claude-sonnet-5-5"
MAX_TOKENS = 4000
AUDIT_PATH = LOG_DIR / "audit.jsonl"
APP_LOG_PATH = LOG_DIR / "glrecon.log"

# USD per 1M tokens: (input, output, cache read). Cache writes (5-minute TTL) cost 1.25x input.
# Check https://platform.claude.com/docs/en/about-claude/pricing before relying on these.
# A model not listed here is still called; its cost is reported as $0 with a warning in the log.
PRICES = {
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00"), Decimal("0.10")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00"), Decimal("0.20")),
}
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
