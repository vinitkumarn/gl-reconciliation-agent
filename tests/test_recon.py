"""recon.sql: balances and candidates tie to the planted plan."""
from __future__ import annotations

import shutil
from decimal import Decimal

import duckdb

from glrecon import db


def test_zero_unexplained_in_all_30_cases(world):
    con = db.connect(world.db_path)
    rows = con.execute("SELECT ledger_id, difference, candidate_total, unexplained "
                       "FROM recon_summary ORDER BY ledger_id").fetchall()
    con.close()
    assert len(rows) == 30
    for ledger, diff, total, unexplained in rows:
        assert unexplained == Decimal("0.00"), ledger
        assert diff == total, ledger


def test_balances_match_plan(world, facts):
    for cid, case in world.cases.items():
        f = facts[cid]
        assert f.sl_end == Decimal(case["sl_end"]), cid
        assert f.gl_end == Decimal(case["gl_end"]), cid
        assert f.difference == Decimal(case["difference"]), cid


def test_candidates_match_planted_items_by_evidence(world, facts):
    for cid, case in world.cases.items():
        got = {frozenset(c.evidence_ids): (c.pattern, c.amount) for c in facts[cid].candidates}
        want = {frozenset(i["evidence_ids"]): (i["pattern"], Decimal(i["amount"]))
                for i in case["items"]}
        assert got == want, cid


def test_c12_offsetting_has_two_candidates_and_zero_difference(facts):
    f = facts["C12"]
    assert f.difference == Decimal("0.00")
    assert sorted(c.amount for c in f.candidates) == [Decimal("-5000.00"), Decimal("5000.00")]


def test_third_duplicate_copy_is_not_double_counted(world, tmp_path):
    path = tmp_path / "copy.duckdb"
    shutil.copy(world.db_path, path)
    con = duckdb.connect(str(path))
    dup = next(c for c in world.cases["C06"]["items"] if c["pattern"] == "DUPLICATE_JE")
    second = int(dup["evidence_ids"][1].split(":")[1])
    con.execute("INSERT INTO gl_je_headers SELECT 999001, ledger_id, je_source, period_name, "
                "status, import_ref, accrual_rev_period, accrual_rev_status, description "
                "FROM gl_je_headers WHERE je_header_id = ?", [second])
    con.execute("INSERT INTO gl_je_lines SELECT 999001, je_line_num, account, accounted_dr, "
                "accounted_cr, gl_sl_link_id FROM gl_je_lines WHERE je_header_id = ?", [second])
    db.run_recon(con)
    rows = con.execute("SELECT item_id, amount, evidence_ids FROM recon_candidates "
                       "WHERE ledger_id = 'C06' AND pattern = 'DUPLICATE_JE'").fetchall()
    con.close()
    assert len(rows) == 2                          # copy 2 and copy 3, once each
    assert len({r[0] for r in rows}) == 2
    assert all(r[1] == Decimal(dup["amount"]) for r in rows)
    first = dup["evidence_ids"][0]
    assert sorted(r[2][1] for r in rows) == sorted([dup["evidence_ids"][1], "JE:999001"])
    assert all(r[2][0] == first for r in rows)
