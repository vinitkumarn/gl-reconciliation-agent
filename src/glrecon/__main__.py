"""Command line: python -m glrecon build | run --case C01 --by claude
| eval --by claude [--cases C01,C27] [--limit N]"""
from __future__ import annotations

import argparse
import logging

from . import baselines, config, db, evaluate, explainer, generator, report

EXPLAINERS = sorted([*baselines.BASELINES, "claude"])


def _setup_logging() -> None:
    """Full messages (API errors, invalid answers) go to logs/glrecon.log."""
    logger = logging.getLogger("glrecon")
    if logger.handlers:
        return
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(config.APP_LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _case_list(text: str) -> list[str]:
    return [c.strip().upper() for c in text.split(",") if c.strip()]


def main(argv: list[str] | None = None, client=None) -> int:
    try:
        return _main(argv, client)
    except TypeError as e:  # the SDK raises TypeError when it finds no credentials
        if "Could not resolve authentication" not in str(e):
            raise
        print("No Anthropic credentials found. Put ANTHROPIC_API_KEY=... in .env "
              "(see .env.example), then run again.")
        return 2


def _main(argv: list[str] | None, client) -> int:
    parser = argparse.ArgumentParser(prog="glrecon", description="GL Reconciliation Explainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="make the synthetic CSVs, data/plan.json and the DuckDB file")
    run_p = sub.add_parser("run", help="reconcile one case")
    run_p.add_argument("--case", required=True, help="case id, e.g. C01")
    eval_p = sub.add_parser("eval", help="grade the cases against the planted plan")
    eval_p.add_argument("--cases", type=_case_list, default=None,
                        help="only these case ids, comma separated, e.g. C01,C27")
    eval_p.add_argument("--limit", type=int, default=None, help="only the first N cases")
    for p in (run_p, eval_p):
        p.add_argument("--by", choices=EXPLAINERS, default="rules")
        p.add_argument("--no-cache", action="store_true",
                       help="ignore the response cache and call the API fresh")
    args = parser.parse_args(argv)
    _setup_logging()

    if args.command == "build":
        plan = generator.build(config.CSV_DIR, config.PLAN_PATH)
        for case in plan["cases"]:
            patterns = ", ".join(f"{i['pattern']} {i['amount']}" for i in case["items"]) or "none"
            print(f"{case['case_id']}  difference {case['difference']:>10}  {patterns}")
        print(f"Wrote {len(plan['cases'])} cases to {config.CSV_DIR} and {config.PLAN_PATH}")
        db.build_db(config.CSV_DIR, config.DB_PATH)
        print(f"Built {config.DB_PATH} (all 3 data checks passed)")
    elif args.command == "run":
        con = db.connect(config.DB_PATH)
        try:
            result = explainer.run_case(con, args.case.upper(), args.by, client=client,
                                        cache_dir=config.CACHE_DIR,
                                        audit_path=config.AUDIT_PATH, no_cache=args.no_cache)
        finally:
            con.close()
        text = report.render(result)
        print(text)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = config.REPORTS_DIR / f"{result.case_id}_{args.by}.md"
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path}")
    elif args.command == "eval":
        try:
            m = evaluate.evaluate(args.by, config.DB_PATH, config.PLAN_PATH, config.REPORTS_DIR,
                                  client=client, cache_dir=config.CACHE_DIR,
                                  audit_path=config.AUDIT_PATH, no_cache=args.no_cache,
                                  cases=args.cases, limit=args.limit)
        except evaluate.CaseSelectionError as e:
            print(f"Error: {e}")
            return 2
        print(f"Gross dollars explained correctly: {m['gross_dollars_pct']}%  "
              f"status accuracy: {m['status_accuracy']}%")
        if args.by == "claude":
            print(f"Cost ${m['cost_total']:.4f}  cache hit rate {m['cache_hit_rate']}%  "
                  f"saved ${m['cost_saved_total']:.4f}")
        print(f"Wrote {config.REPORTS_DIR / f'eval_{args.by}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
