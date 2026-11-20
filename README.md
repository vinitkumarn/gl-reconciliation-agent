# GL Reconciliation Explainer

For one period (OCT-26), the AP subledger and the GL AP control account (2100) don't agree.
DuckDB SQL computes both balances and finds every candidate reconciling item. Then one Claude
API call per case classifies and explains each item. It **suggests**; a human decides. It never
posts journals. Synthetic data only, USD only, one period, local DuckDB only.

See [docs/design.md](docs/design.md) for the design and [CLAUDE.md](CLAUDE.md) for the project rules.

## Status
- PR 1 (this): package skeleton and the planted synthetic data (30 cases + `data/plan.json`).

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

This writes one CSV per table to `data/csv/` (every case has its own `ledger_id`, C01..C30) and
the answer key to `data/plan.json`. Both are gitignored and are rebuilt the same way every time
(fixed seed).

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
