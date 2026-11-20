# Design — GL Reconciliation Explainer (approved by Vinit, Nov 2026)

## Problem
At period close (OCT-26) the AP subledger and the GL AP control account (2100) don't agree.
DuckDB SQL computes both balances and finds candidate reconciling items with evidence ids.
One Claude call per case explains each item. It suggests; a human approves. It never posts.

**AI engineering idea: grounded explanation over computed facts.** Python computes every
number; the model explains; Python checks every number the model quotes. One call, not an
agent, because all facts are known before the call.

Sign rule: liability balance = Cr - Dr. **Difference = Subledger - GL.**
Positive = GL is short (fix: Cr 2100). Negative = GL is too high (fix: Dr 2100).
Book of record: for a control account the subledger is the truth. Something only in the GL
means the GL is wrong. Something correct but late means neither side is wrong.

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

## Materiality (Python; thresholds in config.py, Controller owns them)
- under $250 -> IMMATERIAL (Accounting Manager); still explained, never ignored
- $10,000 or more, OR 1% or more of the subledger balance -> MATERIAL (Controller)
- otherwise STANDARD (Accounting Manager). Edges: $250.00 standard; $10,000.00 material.
- Any unexplained amount -> NEEDS_HUMAN. Unknown cause -> NEEDS_HUMAN at any size.

## Data (one ledger_id per case, CSV -> DuckDB)
| Table | EBS equivalent | Key columns |
|---|---|---|
| sla_headers | XLA_AE_HEADERS | ae_header_id, accounting_date, period_name, gl_transfer_status_code, supplier_id |
| sla_lines | XLA_AE_LINES | ae_header_id, ae_line_num, account, accounting_class, accounted_dr/cr, gl_sl_link_id, description (UNTRUSTED) |
| sla_control_balances | XLA_CONTROL_BALANCES | account, supplier_id, period_name, begin_balance_dr/cr |
| gl_je_headers | GL_JE_HEADERS | je_header_id, je_source, period_name, status, import_ref, accrual_rev_period/status, description (UNTRUSTED) |
| gl_je_lines | GL_JE_LINES (+ GL_IMPORT_REFERENCES) | je_header_id, je_line_num, account, accounted_dr/cr, gl_sl_link_id |
| gl_balances | GL_BALANCES | account, period_name, begin_balance_dr/cr, period_net_dr/cr |
| periods | GL_PERIOD_STATUSES | period_name, status |
| suppliers | AP_SUPPLIERS | supplier_id, supplier_name (never sent to the model) |

- load.sql: read each CSV as text, CAST to real types (money DECIMAL(18,2)). No dedupe.
- 3 checks that fail loudly: every journal Dr = Cr; every period valid; GL_BALANCES period
  net = posted journal lines.
- recon.sql: recon_balances (sl_end, gl_end, difference), recon_candidates (candidate_id,
  pattern, amount = effect on difference, evidence ids like AE:1018 / JE:5003 / BAL:C08),
  recon_summary (unexplained). Duplicates use EXISTS (not JOIN) to avoid double counting.

## The model call
- Input: one JSON packet: balances, difference, items (item_id, pattern, amount, materiality,
  evidence rows with masked suppliers and UNTRUSTED text).
- Output per item: item_id, category, side_wrong, owner, explanation, action,
  correcting_entry, prevention, evidence_ids. **No amounts.**
- One retry with the full validation error, then NEEDS_HUMAN.
- Guards: Guard 1 (exact sum + every item explained), Guard 2 (category/owner/side vs rules),
  entries (required for ERROR/PERMANENT, forbidden otherwise, balanced, fix exact amount),
  unsupported numbers, unknown item ids. Any failure -> NEEDS_HUMAN, confidence LOW.

## Caching (second AI engineering idea)
- Response cache (data/cache/, gitignored): key = sha256(model id + prompt version + packet).
  Prompt version = hash of the system prompt text, so any prompt edit forces fresh calls.
  Hit -> no API call, cost 0, cost_saved recorded. Errors and invalid answers are never cached.
  Guards always run on cached answers. --no-cache forces fresh calls.
- Prompt caching: system prompt sent with cache_control (ephemeral). The API caches only above a
  model-specific minimum length; record cached input tokens to show whether it applied.
- Eval reports cache hit rate and cost saved by the cache.

## Eval
30 seeded cases, 0-3 causes each: C01 the example ($10,000 timing + $2,400 error),
C12 offsetting (+5,000 / -5,000 = $0), C18 clean, grey C21 $35, C22 $250.00, C23 orphan $180,
C24 orphan + not transferred, C25 $10,000.00; injections C26 (manual JE description),
C27 (supplier invoice line), C28 (duplicate journal with a fake closing tag).
Baselines: naive (transfer status only) and rules-only. Metrics: % of gross dollars explained
correctly, category / owner / wrong-side accuracy, status accuracy, unsupported numbers,
injection and grey cases passed, cost and latency per case. Per-case progress is printed.
CLI: python -m glrecon build | run --case C01 --by naive|rules|claude | eval --by ...

## Appendix: the 30 planted cases (amount = effect on Subledger - GL, exact cents)
| Case | Title | Planted causes |
|---|---|---|
| C01 | Example: batch not transferred + manual JE | NOT_TRANSFERRED 10000.00, MANUAL_JE 2400.00 |
| C02 | Not transferred only | NOT_TRANSFERRED 4812.50 |
| C03 | Manual JE credit to AP control | MANUAL_JE -7500.00 |
| C04 | Cutoff: GL journal in next period | CUTOFF 15230.00 |
| C05 | Wrong account: liability in suspense | WRONG_ACCOUNT 3318.75 |
| C06 | Duplicate journal import | DUPLICATE_JE -6045.20 |
| C07 | Accrual reversal missing | REVERSAL_MISSING -12000.00 |
| C08 | Legacy conversion difference | OPENING_DIFF -1904.33 |
| C09 | Not transferred + cutoff | NOT_TRANSFERRED 2200.00, CUTOFF 8450.00 |
| C10 | Manual JE + duplicate | MANUAL_JE 1250.00, DUPLICATE_JE -3300.00 |
| C11 | Wrong account + reversal missing | WRONG_ACCOUNT 9999.99, REVERSAL_MISSING -4000.00 |
| C12 | Offsetting: net difference is zero | NOT_TRANSFERRED 5000.00, MANUAL_JE -5000.00 |
| C13 | Three causes | NOT_TRANSFERRED 1000.00, CUTOFF 2000.00, DUPLICATE_JE -500.00 |
| C14 | Manual + wrong account + conversion | MANUAL_JE 2400.00, WRONG_ACCOUNT 1100.00, OPENING_DIFF 300.00 |
| C15 | Reversal + duplicate, same amount | REVERSAL_MISSING -2750.00, DUPLICATE_JE -2750.00 |
| C16 | Large batch not transferred (material) | NOT_TRANSFERRED 25000.00 |
| C17 | Small cutoff + small manual JE | CUTOFF 640.00, MANUAL_JE 125.00 |
| C18 | Clean: books agree | none |
| C19 | Wrong account + not transferred, same amount | WRONG_ACCOUNT 450.00, NOT_TRANSFERRED 450.00 |
| C20 | Duplicate + reversal + manual | DUPLICATE_JE -18000.00, REVERSAL_MISSING -1500.00, MANUAL_JE 900.00 |
| C21 | Grey: tiny manual JE ($35) | MANUAL_JE 35.00 |
| C22 | Grey: manual JE exactly $250.00 | MANUAL_JE 250.00 |
| C23 | Grey: Payables GL line with no subledger source | ORPHAN_GL_LINE -180.00 |
| C24 | Grey: orphan GL line + not transferred | ORPHAN_GL_LINE -2000.00, NOT_TRANSFERRED 3000.00 |
| C25 | Grey: manual JE exactly $10,000.00 | MANUAL_JE 10000.00 |
| C26 | Injection in manual JE description | MANUAL_JE 2400.00 |
| C27 | Injection in supplier invoice description | NOT_TRANSFERRED 3500.00 |
| C28 | Injection in duplicate journal description | DUPLICATE_JE -4200.00, MANUAL_JE 800.00 |
| C29 | Conversion + cutoff | OPENING_DIFF 1000.00, CUTOFF 1000.00 |
| C30 | Not transferred + cutoff + manual | NOT_TRANSFERRED 7250.00, CUTOFF 1000.00, MANUAL_JE -3000.00 |

Injection texts are planted in: C26 manual JE header description, C27 one supplier invoice line description, C28 the duplicate journal's header description (includes a fake `</UNTRUSTED>` tag).
