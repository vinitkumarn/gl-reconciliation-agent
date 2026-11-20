# GL Reconciliation Explainer

For one period (OCT-26), the AP subledger and the GL AP control account (2100) don't agree.
DuckDB SQL computes both balances and finds every candidate reconciling item. Then **one Claude
API call per case** classifies and explains each item: timing, error, permanent or unknown;
which side is wrong; who owns the fix; the correcting entry; how to prevent it. It
**suggests**; a human decides. It never posts journals. Synthetic data only, USD only, one
period, local DuckDB only.

See [docs/design.md](docs/design.md) for the design and [CLAUDE.md](CLAUDE.md) for the project rules.

## The AI idea: grounded explanation over computed facts

- **Python does all the math.** SQL and Python compute the balances, the difference
  (subledger - GL), every candidate item and its signed amount, materiality and approver. The
  model's output schema has **no amount fields**; Python attaches amounts by `item_id`.
- **The model explains.** It gets one JSON facts packet and returns one JSON answer, validated
  with Pydantic (one retry that carries the full validation error).
- **Python checks the answer.** Guards run on every answer, cached or not:
  - Guard 1: the items add up to the difference exactly (to the cent) and every item is explained.
  - Guard 2: category, wrong side and owner agree with the rules.
  - Entries: required for ERROR / PERMANENT, forbidden for TIMING / UNKNOWN, Dr = Cr, and they
    move 2100 by exactly the item amount using the right offset account.
  - Numbers: every number in the text must be grounded: computed by Python, or present in a
    **trusted** part of the packet (amounts, balances, accounts, ids, line numbers, dates).
    A number that appears only in supplier-written `<UNTRUSTED>` text is flagged.
  - Any failure -> `NEEDS_HUMAN` with LOW confidence. Confidence is set by Python, never by the model.
- **Why one call, not an agent.** All the facts are known before the call. There is nothing for
  an agent to go and look up, so a tool loop would only add cost, latency and ways to go wrong.
- **Untrusted text.** Supplier names are masked (`SUPPLIER_A`, ...). Every free-text
  description is wrapped as `<UNTRUSTED>...</UNTRUSTED>` with `<` and `>` escaped, so planted
  prompt injections (C26, C27, C28) can't close the tag or pose as instructions.

## Causes (pattern -> rules)

| Pattern | Type | Wrong side | Owner | Correcting entry | Prevention |
|---|---|---|---|---|---|
| NOT_TRANSFERRED: in SLA, transfer status N | TIMING | NEITHER | AP | None: run Transfer to GL, post | Close checklist: untransferred = 0 |
| CUTOFF: SL in OCT-26, GL journal in NOV-26 | TIMING | NEITHER | AP | None (accrue only if Controller decides) | GL date = accounting date at transfer |
| MANUAL_JE: non-Payables journal on 2100 | ERROR | GL | GL Accounting | Reverse it, offset 6100 | Third-party control account flag |
| WRONG_ACCOUNT: SL line posted to 2999 | ERROR | GL | GL Accounting | Dr 2999 / Cr 2100 | Suspense = 0 before close |
| DUPLICATE_JE: same import_ref twice | ERROR | GL | GL Accounting | Reverse duplicate, offset 6100 | Block re-import of an import_ref |
| REVERSAL_MISSING: SEP-26 accrual not reversed | ERROR | GL | GL Accounting | Post reversal, offset 6100 | Auto-reversal + checklist |
| OPENING_DIFF: conversion difference | PERMANENT | GL | Controller | True-up, offset 3900 | Signed tie-out at conversion |
| ORPHAN_GL_LINE: Payables GL line, no SL link | UNKNOWN | UNKNOWN | GL Accounting | None: investigate | Alert on unlinked Payables lines |

Materiality (Python, thresholds in `config.py`): under $250 IMMATERIAL; $10,000 or more, or 1% or
more of the subledger balance, MATERIAL (Controller); otherwise STANDARD. An unknown cause or any
unexplained amount goes to a human at any size.

## Caching

- **Response cache** (`data/cache/`, gitignored). What is cached: the validated answer and what
  it cost. Key = `sha256(model id + prompt version + facts packet)`; the prompt version is a hash
  of the system prompt, so any prompt edit forces fresh calls. A hit makes no API call, costs $0
  and records the cost saved. API errors and invalid answers are never cached. **Guards always
  run on cached answers.** `--no-cache` forces fresh calls.
- **Prompt caching.** The system prompt is sent with `cache_control` (ephemeral); cached input
  tokens are recorded per case so you can see whether the API applied it (it only does above a
  model-specific minimum length).
- The eval reports cache hit rate and cost saved.

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

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` (only `--by claude` needs it).
`GLRECON_MODEL` is optional; it defaults to `claude-sonnet-5-5`.

## Build the data

```powershell
python -m glrecon build
```

This writes one CSV per table to `data/csv/` (every case has its own `ledger_id`, C01..C30),
the answer key to `data/plan.json`, and loads it all into `data/glrecon.duckdb` (`sql/load.sql`,
then the 3 data checks, then `sql/recon.sql`). All are gitignored and rebuilt the same way every
time (fixed seed).

## Reconcile one case, or grade the cases

```powershell
python -m glrecon run --case C01 --by rules
```

```powershell
python -m glrecon eval --by rules
```

```powershell
python -m glrecon eval --by naive
```

```powershell
python -m glrecon run --case C01 --by claude
```

```powershell
python -m glrecon eval --by claude
```

Run only some cases (cheap re-checks of a few real calls):

```powershell
python -m glrecon eval --by claude --cases C01,C27
```

```powershell
python -m glrecon eval --by claude --limit 5
```

`--by claude` makes one Claude API call per case (needs `ANTHROPIC_API_KEY` in `.env`). Answers
are cached in `data/cache/`, so a second `eval --by claude` costs $0; add `--no-cache` to force
fresh calls. Every run appends one line to `logs/audit.jsonl` (ids, hashes, tokens, status only;
no raw text, no supplier names); full API error messages go to `logs/glrecon.log`.

`run` prints the report and saves `reports/C01_rules.md`. `eval` prints per-case progress and
saves `reports/eval_rules.md` (or `eval_naive.md`, `eval_claude.md`).

## Run the tests

```powershell
python -m pytest
```

The tests never call the real API; the model call is tested with a scripted fake client.

## Results (30 cases, 48 planted items)

| Metric | Naive | Rules | Claude |
|---|---:|---:|---:|
| Gross dollars explained correctly | 30.8% | 100.0% | 100.0% ($201,890.77 of $201,890.77) |
| Category accuracy | 20.8% | 100.0% | 100.0% |
| Wrong-side accuracy | 20.8% | 100.0% | 100.0% |
| Owner accuracy | 20.8% | 100.0% | 100.0% |
| Status accuracy | 20.0% | 100.0% | 100.0% (first real run: 96.7%) |
| Unsupported numbers | 0 | 0 | 0 |
| Injection cases passed | 1/3 | 3/3 | 3/3 |
| Grey cases passed | 0/5 | 5/5 | 5/5 |
| Cost per case | $0 | $0 | about $0.008 fresh; $0 on re-run |
| Time per call | - | - | about 3-9 s fresh; about 12 ms cached |

Claude column: real runs on my laptop with `claude-sonnet-5-5`, 30 cases, 48 planted items,
$201,890.77 gross.

- **Naive** looks only at transfer status, so it can only explain untransferred entries.
- **Rules** applies the causes table directly. Honest note: it scores 100% because the same
  author planted the data and wrote the rules. It is the bar, not a finding. The interesting
  question is whether the model reaches that bar while reading messy evidence and ignoring
  injected instructions, and whether the guards catch it when it doesn't.

**Cost and caching (real runs)**
- Fresh run: $0.2307 for 30 cases (about $0.008 per case), about 3-9 s per call.
- Re-run: 100% response-cache hits, $0.0000, about 12 ms per case, saved $0.2499.
  The guards still ran on every cached answer.
- Prompt caching: after the first call, each call read 1,881 cached system-prompt tokens.
  That roughly halved the cost per case (C01 $0.0134 uncached vs about $0.006 for later cases).

**History: the first real run** (before PR 4): 100% of gross dollars explained correctly,
48/48 items correct, status accuracy 96.7%. The one miss was C27: correct TIMING
classification, injection correctly ignored, but the unsupported-number check flagged "line 2"
(a real line number from the evidence) and sent the case to `NEEDS_HUMAN`. PR 4 fixed this: a
number is grounded when a trusted part of the packet contains it. The re-run after PR 4 gives
the 100% status accuracy in the table.

## What I learned
1. **My own guard caused the only miss.** The model got C27 right; the unsupported-number
   check was too blunt and treated "line 2" from the evidence as an invented number. I fixed
   the guard (a number counts as grounded only when a trusted part of the facts packet
   contains it) rather than loosening it or switching it off.
2. **A balanced entry can still be wrong.** A suggested correction of Dr Cash / Cr AP balances
   (Dr = Cr) and moves the AP control account by the right amount, yet it would create cash
   that does not exist. So the check also requires the offset account the rules expect
   (for example 6100 or 3900), not just any balancing line.
3. **Zero net difference is not "nothing to do".** In C12 a +$5,000 untransferred entry and a
   -$5,000 manual journal cancel out to $0. The sum check passes, but both items are still
   real problems, so every candidate item must be explained before the case can be OK.

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

## Status
- PR 1: package skeleton and the planted synthetic data (30 cases + `data/plan.json`).
- PR 2: DuckDB load + 3 data checks, recon SQL (8 patterns), rules, guards, baselines, eval.
- PR 3: the single Claude call per case, response cache, prompt caching, audit log, cost and latency.
- PR 4: fixes from the first real eval (numbers grounded in trusted packet text, injection note
  only when needed, `eval --cases / --limit`) and this README.
- PR 5: README results from the real laptop runs (no code changes).
