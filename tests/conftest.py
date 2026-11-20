"""Shared fixture: build CSVs, plan.json and the DuckDB file once, in a temp folder."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from glrecon import config, db, generator


@pytest.fixture(autouse=True)
def _no_writes_into_the_repo(tmp_path, monkeypatch):
    """Audit log and response cache default to repo folders; keep tests out of them."""
    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "default-audit.jsonl")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "default-cache")


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("world")
    plan = generator.build(csv_dir=out / "csv", plan_path=out / "plan.json")
    db.build_db(out / "csv", out / "glrecon.duckdb")
    return SimpleNamespace(root=out, csv_dir=out / "csv", plan_path=out / "plan.json",
                           db_path=out / "glrecon.duckdb", plan=plan,
                           cases={c["case_id"]: c for c in plan["cases"]})


@pytest.fixture(scope="session")
def facts(world):
    con = db.connect(world.db_path)
    try:
        return {cid: db.case_facts(con, cid) for cid in db.case_ids(con)}
    finally:
        con.close()


@pytest.fixture
def plan_json(world):
    return json.loads(world.plan_path.read_text(encoding="utf-8"))
