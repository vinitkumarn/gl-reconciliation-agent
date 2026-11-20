"""Command line: python -m glrecon build | run --case C01 --by rules | eval --by rules"""
from __future__ import annotations

import argparse

from . import baselines, config, db, evaluate, generator, guards, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glrecon", description="GL Reconciliation Explainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="make the synthetic CSVs, data/plan.json and the DuckDB file")
    run_p = sub.add_parser("run", help="reconcile one case")
    run_p.add_argument("--case", required=True, help="case id, e.g. C01")
    run_p.add_argument("--by", choices=sorted(baselines.BASELINES), default="rules")
    eval_p = sub.add_parser("eval", help="grade all 30 cases against the planted plan")
    eval_p.add_argument("--by", choices=sorted(baselines.BASELINES), default="rules")
    args = parser.parse_args(argv)

    if args.command == "build":
        plan = generator.build()
        for case in plan["cases"]:
            patterns = ", ".join(f"{i['pattern']} {i['amount']}" for i in case["items"]) or "none"
            print(f"{case['case_id']}  difference {case['difference']:>10}  {patterns}")
        print(f"Wrote {len(plan['cases'])} cases to {config.CSV_DIR} and {config.PLAN_PATH}")
        db.build_db(config.CSV_DIR, config.DB_PATH)
        print(f"Built {config.DB_PATH} (all 3 data checks passed)")
    elif args.command == "run":
        con = db.connect()
        try:
            facts = db.case_facts(con, args.case.upper())
        finally:
            con.close()
        result = guards.finalize(facts, baselines.BASELINES[args.by](facts), args.by)
        text = report.render(result)
        print(text)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = config.REPORTS_DIR / f"{facts.case_id}_{args.by}.md"
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path}")
    elif args.command == "eval":
        m = evaluate.evaluate(args.by)
        print(f"Gross dollars explained correctly: {m['gross_dollars_pct']}%  "
              f"status accuracy: {m['status_accuracy']}%")
        print(f"Wrote {config.REPORTS_DIR / f'eval_{args.by}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
