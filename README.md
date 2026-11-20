# GL Reconciliation Explainer

For one period (OCT-26), the AP subledger and the GL AP control account (2100) don't agree.
DuckDB SQL computes both balances and finds every candidate reconciling item. Then one Claude
API call per case classifies and explains each item. It **suggests**; a human decides. It never
posts journals. Synthetic data only, USD only, one period, local DuckDB only.

See [docs/design.md](docs/design.md) for the design and [CLAUDE.md](CLAUDE.md) for the project rules.

## Status
- PR 1: package skeleton and the planted synthetic data (30 cases + `data/plan.json`).
- PR 2 (this): DuckDB load + 3 data checks, recon SQL (8 patterns), rules, guards, naive and
  rules baselines, eval. No model call yet.

## Setup on Windows (PowerShell, Python 3.14)

```powershell
py -3.14 -m venv .venv
```

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install -r requirements.txt
```

```powershell
python -m pip install -e .
```

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` (needed only from the model-call
PR onward). `GLRECON_MODEL` is optional; it defaults to `claude-sonnet-5-5`.

## Build the data

```powershell
python -m glrecon build
```

This writes one CSV per table to `data/csv/` (every case has its own `ledger_id`, C01..C30),
the answer key to `data/plan.json`, and loads it all into `data/glrecon.duckdb` (`sql/load.sql`,
then the 3 data checks, then `sql/recon.sql`). All are gitignored and rebuilt the same way every
time (fixed seed).

## Reconcile one case, or grade all 30

```powershell
python -m glrecon run --case C01 --by rules
```

```powershell
python -m glrecon eval --by rules
```

```powershell
python -m glrecon eval --by naive
```

`run` prints the report and saves `reports/C01_rules.md`. `eval` prints per-case progress and
saves `reports/eval_rules.md` (or `eval_naive.md`).

## Run the tests

```powershell
python -m pytest
```

## Data tables (CSV)
| File | EBS equivalent |
|---|---|
| sla_headers.csv | XLA_AE_HEADERS |
| sla_lines.csv | XLA_AE_LINES |
| sla_control_balances.csv | XLA_CONTROL_BALANCES |
| gl_je_headers.csv | GL_JE_HEADERS |
| gl_je_lines.csv | GL_JE_LINES (+ GL_IMPORT_REFERENCES) |
| gl_balances.csv | GL_BALANCES |
| periods.csv | GL_PERIOD_STATUSES |
| suppliers.csv | AP_SUPPLIERS |
