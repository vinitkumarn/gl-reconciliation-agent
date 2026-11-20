"""Command line: python -m glrecon build"""
from __future__ import annotations

import argparse

from . import config, generator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glrecon", description="GL Reconciliation Explainer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="make the synthetic CSV files and data/plan.json")
    args = parser.parse_args(argv)

    if args.command == "build":
        plan = generator.build()
        for case in plan["cases"]:
            patterns = ", ".join(f"{i['pattern']} {i['amount']}" for i in case["items"]) or "none"
            print(f"{case['case_id']}  difference {case['difference']:>10}  {patterns}")
        print(f"Wrote {len(plan['cases'])} cases to {config.CSV_DIR} and {config.PLAN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
