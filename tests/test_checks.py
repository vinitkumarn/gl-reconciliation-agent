"""The 3 data checks fail loudly on bad data."""
from __future__ import annotations

import csv
import shutil
from decimal import Decimal

import pytest

from glrecon import db


def corrupt(world, tmp_path, table: str, change) -> tuple:
    csv_dir = tmp_path / "csv"
    shutil.copytree(world.csv_dir, csv_dir)
    path = csv_dir / f"{table}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    change(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return csv_dir, tmp_path / "bad.duckdb"


def bump(field):
    def change(row):
        row[field] = f"{Decimal(row[field]) + Decimal('0.01'):.2f}"
    return change


def test_clean_data_passes(world, tmp_path):
    db.build_db(world.csv_dir, tmp_path / "ok.duckdb")


def test_unbalanced_journal_fails(world, tmp_path):
    csv_dir, path = corrupt(world, tmp_path, "sla_lines", bump("accounted_dr"))
    with pytest.raises(db.DataCheckError) as e:
        db.build_db(csv_dir, path)
    assert e.value.check == "check_journals_balance"


def test_invalid_period_fails(world, tmp_path):
    csv_dir, path = corrupt(world, tmp_path, "sla_headers",
                            lambda r: r.update(period_name="DEC-26"))
    with pytest.raises(db.DataCheckError) as e:
        db.build_db(csv_dir, path)
    assert e.value.check == "check_valid_periods"


def test_gl_balances_not_tied_to_journals_fails(world, tmp_path):
    csv_dir, path = corrupt(world, tmp_path, "gl_balances", bump("period_net_dr"))
    with pytest.raises(db.DataCheckError) as e:
        db.build_db(csv_dir, path)
    assert e.value.check == "check_gl_balances_tie"
