# GL Reconciliation Explainer — project rules

## What this is
A portfolio project by Vinit (Oracle ERP techno-functional, 12+ years AP/AR/GL/SLA).
For one period, the AP subledger and the GL AP control account don't agree. DuckDB SQL
computes the balances and finds every candidate reconciling item. Then ONE Claude API call
per case classifies and explains each item. It SUGGESTS; a human decides. It never posts
journals. Synthetic data only. USD only. One period. Local DuckDB only.

The design is in docs/design.md. Follow it. If something in it seems wrong, say so in
the PR description instead of silently changing it.

## Keep it simple (on purpose)
- No agent loop and no tools: all facts are known before the call, so the model gets one
  JSON packet of facts. No MCP. No approval CLI. No raw/clean pipeline layers.
- One load.sql (CSV -> typed tables) and one recon.sql (balances + candidates).
- Only 3 data checks: every journal balances, valid periods, GL_BALANCES ties to journals.
- Prefer the simplest code that meets the design. Don't add features that aren't in it.

## Non-negotiable design rules
- Python does ALL math: balances, the difference, candidate items, materiality, the sum
  check, and that every suggested correcting entry balances (Dr = Cr) AND moves the AP
  control account by exactly the item amount. The model's output schema has NO amount
  fields; Python attaches amounts by item_id.
- Guard 1: items must add up EXACTLY to the difference (Decimal, to the cent) AND every
  candidate item must be explained. Anything unexplained -> NEEDS_HUMAN.
- Guard 2: if the model's category, owner or wrong side disagrees with the rules ->
  NEEDS_HUMAN. Confidence is set by Python, never self-reported.
- Timing and unknown items get NO correcting entry. Error and permanent items must.
- Every number in the model's text must be a number Python computed (unsupported-number check).
- Pydantic-validated output with ONE retry that includes the full validation error.
- JSON-lines audit log with ids and hashes only (no raw text, no supplier names).
- Supplier names masked; free text wrapped as <UNTRUSTED> with < and > escaped.
- Caching: response cache keyed by sha256(model + prompt version + facts packet). Never cache
  API errors or invalid answers. Guards ALWAYS run, even on cached answers. --no-cache forces
  fresh calls. Mark the system prompt with cache_control and record cached input tokens.
- Eval labels come from the planted plan (plan.json), NEVER from the rules code. Match
  report items to planted items by evidence ids, not by amount.
- Money is Decimal, never float. Edge-case test data uses exact numbers
  (249.99 / 250.00 / 9,999.99 / 10,000.00 / exactly 1%).
- LLM: Anthropic Claude, model from GLRECON_MODEL in .env (default claude-sonnet-5-5),
  max_tokens 4000, full error messages in logs.

## Working rules
- Never commit .env or any secret. .gitignore covers .env, .venv/, *.db, *.duckdb, logs/,
  *.egg-info/, data/csv/, data/plan.json, data/cache/, reports/.
- There is no API key in this sandbox. Never call the real Claude API here. Test the
  model call with a scripted fake client. Vinit runs real evals on his laptop.
- One milestone per PR. All tests must pass before you stop.
- Every PR description must include, in simple everyday language:
  1. What this PR adds and why
  2. A short "what to review" checklist (the 3-5 things most worth checking)
  3. Accounting-judgment notes where relevant (timing vs error vs permanent, which side
     is wrong, owner, correcting entry, prevention, dollars at risk)
  4. How to test it on Windows PowerShell: py launcher (Python 3.14), venv activated with
     Set-ExecutionPolicy -Scope Process Bypass then .venv\Scripts\Activate.ps1, python -m pip
  5. Any new Python concept explained in 2-3 plain sentences
