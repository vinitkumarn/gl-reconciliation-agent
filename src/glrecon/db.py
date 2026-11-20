"""DuckDB: load the CSVs (load.sql), run the 3 loud data checks, run recon.sql, read case facts."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import duckdb

from . import config

# Check view name -> what it means. Order matters: the first failing check is reported.
CHECKS = {
    "check_journals_balance": "every journal must balance (Dr = Cr)",
    "check_valid_periods": "every period must be a valid period of its ledger",
    "check_gl_balances_tie": "GL_BALANCES period net must equal the posted journal lines",
}


class DataCheckError(Exception):
    """A data check failed. The data is bad; nothing downstream can be trusted."""

    def __init__(self, check: str, rows: list[tuple]):
        self.check = check
        self.rows = rows
        sample = "\n  ".join(str(r) for r in rows[:5])
        super().__init__(f"DATA CHECK FAILED: {check} ({CHECKS[check]}); "
                         f"{len(rows)} bad row(s):\n  {sample}")


@dataclass(frozen=True)
class Candidate:
    item_id: str
    pattern: str
    amount: Decimal          # signed effect on (Subledger - GL)
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaseFacts:
    case_id: str
    period: str
    sl_end: Decimal
    gl_end: Decimal
    difference: Decimal
    candidates: tuple[Candidate, ...]


def _sql(name: str) -> str:
    return (config.SQL_DIR / name).read_text(encoding="utf-8")


def load(con: duckdb.DuckDBPyConnection, csv_dir: Path) -> None:
    """Run load.sql: CSV -> typed tables + check views."""
    folder = Path(csv_dir).resolve().as_posix().replace("'", "''")
    con.execute(_sql("load.sql").replace("__CSV_DIR__", folder))


def run_checks(con: duckdb.DuckDBPyConnection) -> None:
    """Fail loudly on the first check view that returns any row."""
    for view in CHECKS:
        rows = con.execute(f"SELECT * FROM {view}").fetchall()
        if rows:
            raise DataCheckError(view, rows)


def run_recon(con: duckdb.DuckDBPyConnection) -> None:
    """Create recon_params from config.py, then run recon.sql."""
    con.execute(
        "CREATE OR REPLACE TABLE recon_params AS SELECT ? AS recon_period, ? AS next_period, "
        "? AS ap_account, ? AS suspense_account",
        [config.RECON_PERIOD, config.NEXT_PERIOD, config.AP_CONTROL, config.SUSPENSE])
    con.execute(_sql("recon.sql"))


def build_db(csv_dir: Path = config.CSV_DIR, db_path: Path = config.DB_PATH) -> None:
    """Build the DuckDB file from the CSVs. Raises DataCheckError on bad data."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        load(con, csv_dir)
        run_checks(con)
        run_recon(con)
    finally:
        con.close()


def connect(db_path: Path = config.DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"{db_path} not found. Run: python -m glrecon build")
    return duckdb.connect(str(db_path), read_only=read_only)


def case_ids(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT ledger_id FROM recon_balances ORDER BY ledger_id").fetchall()]


def case_facts(con: duckdb.DuckDBPyConnection, case_id: str) -> CaseFacts:
    row = con.execute("SELECT sl_end, gl_end, difference FROM recon_balances WHERE ledger_id = ?",
                      [case_id]).fetchone()
    if row is None:
        raise KeyError(f"unknown case {case_id}")
    cands = con.execute(
        "SELECT item_id, pattern, amount, evidence_ids FROM recon_candidates "
        "WHERE ledger_id = ? ORDER BY CAST(split_part(item_id, '-I', 2) AS INTEGER)",
        [case_id]).fetchall()
    return CaseFacts(
        case_id=case_id, period=config.RECON_PERIOD,
        sl_end=row[0], gl_end=row[1], difference=row[2],
        candidates=tuple(Candidate(i, p, a, tuple(e)) for i, p, a, e in cands))
