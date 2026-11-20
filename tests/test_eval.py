"""Eval: rules baseline is perfect, naive baseline is well below half."""
from __future__ import annotations

from decimal import Decimal

import pytest

from glrecon import baselines, db, evaluate, guards, report


@pytest.fixture(scope="module")
def results(world, tmp_path_factory):
    out = tmp_path_factory.mktemp("reports")
    lines = []
    res = {by: evaluate.evaluate(by, world.db_path, world.plan_path, out, echo=lines.append,
                                 audit_path=out / "audit.jsonl", cache_dir=out / "cache")
           for by in ("rules", "naive")}
    return res, out, lines


def test_rules_baseline_is_100_percent(results):
    m = results[0]["rules"]
    for key in ("gross_dollars_pct", "category_accuracy", "side_accuracy", "owner_accuracy",
                "status_accuracy"):
        assert m[key] == Decimal(100), key
    assert m["unsupported_numbers"] == 0
    assert m["injection_passed"] == 3 and m["grey_passed"] == 5


def test_naive_baseline_below_half(results):
    m = results[0]["naive"]
    assert m["gross_dollars_pct"] < 50
    assert m["status_accuracy"] < 100


def test_progress_and_report_written(results):
    _, out, lines = results
    assert len(lines) == 60 and lines[0].startswith("[ 1/30] C01")
    for by in ("rules", "naive"):
        text = (out / f"eval_{by}.md").read_text(encoding="utf-8")
        assert "Gross dollars explained correctly" in text and "| C30 |" in text


def test_labels_come_from_plan_not_rules(world):
    """Grading uses plan labels: a wrong plan label must make the rules baseline 'wrong'."""
    case = dict(world.cases["C01"])
    case["items"] = [dict(i) for i in case["items"]]
    case["items"][0]["owner"] = "Controller"
    con = db.connect(world.db_path)
    f = db.case_facts(con, "C01")
    con.close()
    g = evaluate.grade_case(case, guards.finalize(f, baselines.rules(f), "rules"))
    assert not g["items"][0]["correct"] and g["items"][1]["correct"]


def test_render_case_report(facts):
    text = report.render(guards.finalize(facts["C01"], baselines.rules(facts["C01"]), "rules"))
    assert "READY_FOR_REVIEW" in text and "$12,400.00" in text and "Nothing is posted" in text


# --- eval --cases / --limit (PR 4, Fix 3) ---------------------------------------------------
@pytest.fixture
def cli_world(world, tmp_path, monkeypatch):
    from glrecon import config
    monkeypatch.setattr(config, "DB_PATH", world.db_path)
    monkeypatch.setattr(config, "PLAN_PATH", world.plan_path)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "APP_LOG_PATH", tmp_path / "logs" / "glrecon.log")
    return tmp_path


def test_eval_cases_picks_only_those(cli_world, capsys):
    from glrecon import __main__ as cli
    assert cli.main(["eval", "--by", "rules", "--cases", "c27, C01"]) == 0
    out = capsys.readouterr().out
    assert "[ 1/2] C01" in out and "[ 2/2] C27" in out and "C02" not in out
    text = (cli_world / "reports" / "eval_rules.md").read_text(encoding="utf-8")
    assert "| Injection cases passed | 1/1 |" in text and "| Grey cases passed | 0/0 |" in text


def test_eval_limit_keeps_first_n(cli_world, capsys):
    from glrecon import __main__ as cli
    assert cli.main(["eval", "--by", "rules", "--limit", "3"]) == 0
    out = capsys.readouterr().out
    assert "[ 3/3] C03" in out and "C04" not in out


def test_eval_unknown_case_is_an_error(cli_world, capsys):
    from glrecon import __main__ as cli
    assert cli.main(["eval", "--by", "rules", "--cases", "C01,C99"]) == 2
    assert "unknown case id(s): C99" in capsys.readouterr().out


def test_select_cases_combines_cases_and_limit(world):
    picked = evaluate.select_cases(world.plan["cases"], ["C05", "C02", "C09"], limit=2)
    assert [c["case_id"] for c in picked] == ["C02", "C05"]
