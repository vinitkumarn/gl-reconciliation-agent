-- recon.sql: balances, candidate reconciling items, summary.
-- Needs the one-row table recon_params (recon_period, next_period, ap_account, suspense_account),
-- which Python creates from config.py before running this file.
-- Sign rule: liability = Cr - Dr. Difference = Subledger - GL. Every candidate amount is its
-- signed effect on that difference, so the candidates must add up to the difference exactly.

-- ---------------------------------------------------------------------------
-- Balances
CREATE OR REPLACE TABLE recon_balances AS
WITH p AS (SELECT * FROM recon_params),
ledgers AS (SELECT DISTINCT ledger_id FROM periods),
sl_begin AS (
    SELECT b.ledger_id, SUM(b.begin_balance_cr - b.begin_balance_dr) AS amt
    FROM sla_control_balances b, p
    WHERE b.period_name = p.recon_period AND b.account = p.ap_account
    GROUP BY b.ledger_id
),
sl_move AS (
    SELECT h.ledger_id, SUM(l.accounted_cr - l.accounted_dr) AS amt
    FROM sla_lines l JOIN sla_headers h USING (ae_header_id), p
    WHERE h.period_name = p.recon_period AND l.account = p.ap_account
    GROUP BY h.ledger_id
),
gl AS (
    SELECT g.ledger_id,
           SUM(g.begin_balance_cr - g.begin_balance_dr + g.period_net_cr - g.period_net_dr) AS amt
    FROM gl_balances g, p
    WHERE g.period_name = p.recon_period AND g.account = p.ap_account
    GROUP BY g.ledger_id
),
ends AS (
    SELECT x.ledger_id,
           CAST(COALESCE(sb.amt, 0) + COALESCE(sm.amt, 0) AS DECIMAL(18,2)) AS sl_end,
           CAST(COALESCE(gl.amt, 0) AS DECIMAL(18,2))                       AS gl_end
    FROM ledgers x
    LEFT JOIN sl_begin sb USING (ledger_id)
    LEFT JOIN sl_move sm USING (ledger_id)
    LEFT JOIN gl USING (ledger_id)
)
SELECT ledger_id, sl_end, gl_end, CAST(sl_end - gl_end AS DECIMAL(18,2)) AS difference
FROM ends
ORDER BY ledger_id;

-- ---------------------------------------------------------------------------
-- Candidate reconciling items (all 8 patterns)
CREATE OR REPLACE TABLE recon_candidates AS
WITH p AS (SELECT * FROM recon_params),
-- subledger 2100 lines of the recon period, with their header
sl_ap AS (
    SELECT h.ledger_id, h.ae_header_id, h.gl_transfer_status_code, l.gl_sl_link_id,
           l.accounted_cr - l.accounted_dr AS liability
    FROM sla_lines l JOIN sla_headers h USING (ae_header_id), p
    WHERE h.period_name = p.recon_period AND l.account = p.ap_account
),
-- posted GL lines with their header
gl_posted AS (
    SELECT h.ledger_id, h.je_header_id, h.je_source, h.period_name, h.import_ref,
           h.accrual_rev_period, h.accrual_rev_status,
           l.account, l.gl_sl_link_id, l.accounted_dr - l.accounted_cr AS dr_minus_cr
    FROM gl_je_lines l JOIN gl_je_headers h USING (je_header_id)
    WHERE h.status = 'P'
),
-- 1. In the subledger, never transferred to the GL
not_transferred AS (
    SELECT ledger_id, 'NOT_TRANSFERRED' AS pattern, SUM(liability) AS amount,
           ['AE:' || ae_header_id] AS evidence_ids
    FROM sl_ap
    WHERE gl_transfer_status_code = 'N'
    GROUP BY ledger_id, ae_header_id
),
-- 2. Transferred, but the GL journal sits in the next period
cutoff AS (
    SELECT s.ledger_id, 'CUTOFF' AS pattern, SUM(s.liability) AS amount,
           ['AE:' || s.ae_header_id, 'JE:' || MIN(g.je_header_id)] AS evidence_ids
    FROM sl_ap s
    JOIN gl_posted g ON g.ledger_id = s.ledger_id AND g.gl_sl_link_id = s.gl_sl_link_id, p
    WHERE s.gl_transfer_status_code = 'Y' AND g.period_name = p.next_period
      AND g.je_source = 'Payables' AND g.account = p.ap_account
    GROUP BY s.ledger_id, s.ae_header_id
),
-- 3. A non-Payables journal hitting the AP control account
manual_je AS (
    SELECT g.ledger_id, 'MANUAL_JE' AS pattern, SUM(g.dr_minus_cr) AS amount,
           ['JE:' || g.je_header_id] AS evidence_ids
    FROM gl_posted g, p
    WHERE g.period_name = p.recon_period AND g.je_source <> 'Payables'
      AND g.account = p.ap_account
    GROUP BY g.ledger_id, g.je_header_id
),
-- 4. Subledger liability that reached the GL in the suspense account
wrong_account AS (
    SELECT s.ledger_id, 'WRONG_ACCOUNT' AS pattern, SUM(s.liability) AS amount,
           ['AE:' || s.ae_header_id, 'JE:' || MIN(g.je_header_id)] AS evidence_ids
    FROM sl_ap s
    JOIN gl_posted g ON g.ledger_id = s.ledger_id AND g.gl_sl_link_id = s.gl_sl_link_id, p
    WHERE s.gl_transfer_status_code = 'Y' AND g.period_name = p.recon_period
      AND g.account = p.suspense_account
    GROUP BY s.ledger_id, s.ae_header_id
),
-- 5. The same import_ref imported more than once. EXISTS (not JOIN): each later copy is
--    one candidate, so a third copy is not double counted.
duplicate_je AS (
    SELECT g.ledger_id, 'DUPLICATE_JE' AS pattern, SUM(g.dr_minus_cr) AS amount,
           ['JE:' || (SELECT MIN(f.je_header_id) FROM gl_je_headers f
                      WHERE f.ledger_id = g.ledger_id AND f.import_ref = g.import_ref
                        AND f.je_source = 'Payables' AND f.status = 'P'),
            'JE:' || g.je_header_id] AS evidence_ids
    FROM gl_posted g, p
    WHERE g.period_name = p.recon_period AND g.je_source = 'Payables'
      AND g.account = p.ap_account AND g.import_ref IS NOT NULL
      AND EXISTS (SELECT 1 FROM gl_je_headers e
                  WHERE e.ledger_id = g.ledger_id AND e.import_ref = g.import_ref
                    AND e.je_source = 'Payables' AND e.status = 'P'
                    AND e.je_header_id < g.je_header_id)
    GROUP BY g.ledger_id, g.je_header_id, g.import_ref
),
-- 6. A prior-period accrual flagged to reverse in the recon period, never reversed
reversal_missing AS (
    SELECT g.ledger_id, 'REVERSAL_MISSING' AS pattern, SUM(g.dr_minus_cr) AS amount,
           ['JE:' || g.je_header_id] AS evidence_ids
    FROM gl_posted g, p
    WHERE g.period_name <> p.recon_period AND g.accrual_rev_period = p.recon_period
      AND g.accrual_rev_status = 'N' AND g.account = p.ap_account
    GROUP BY g.ledger_id, g.je_header_id
),
-- 7. Opening (conversion) difference: SL vs GL at the start of the first period
first_period AS (
    SELECT ledger_id, arg_min(period_name, start_date) AS period_name
    FROM periods GROUP BY ledger_id
),
opening_diff AS (
    SELECT f.ledger_id, 'OPENING_DIFF' AS pattern,
           COALESCE((SELECT SUM(b.begin_balance_cr - b.begin_balance_dr)
                     FROM sla_control_balances b, p
                     WHERE b.ledger_id = f.ledger_id AND b.period_name = f.period_name
                       AND b.account = p.ap_account), 0)
         - COALESCE((SELECT SUM(g.begin_balance_cr - g.begin_balance_dr)
                     FROM gl_balances g, p
                     WHERE g.ledger_id = f.ledger_id AND g.period_name = f.period_name
                       AND g.account = p.ap_account), 0) AS amount,
           ['BAL:' || f.ledger_id] AS evidence_ids
    FROM first_period f
),
-- 8. A Payables GL line on 2100 with no subledger link
orphan_gl_line AS (
    SELECT g.ledger_id, 'ORPHAN_GL_LINE' AS pattern, SUM(g.dr_minus_cr) AS amount,
           ['JE:' || g.je_header_id] AS evidence_ids
    FROM gl_posted g, p
    WHERE g.period_name = p.recon_period AND g.je_source = 'Payables'
      AND g.account = p.ap_account
      AND (g.gl_sl_link_id IS NULL
           OR NOT EXISTS (SELECT 1 FROM sla_lines s WHERE s.gl_sl_link_id = g.gl_sl_link_id))
    GROUP BY g.ledger_id, g.je_header_id
),
all_items AS (
    SELECT *, 1 AS rank FROM not_transferred
    UNION ALL SELECT *, 2 FROM cutoff
    UNION ALL SELECT *, 3 FROM manual_je
    UNION ALL SELECT *, 4 FROM wrong_account
    UNION ALL SELECT *, 5 FROM duplicate_je
    UNION ALL SELECT *, 6 FROM reversal_missing
    UNION ALL SELECT *, 7 FROM opening_diff WHERE amount <> 0
    UNION ALL SELECT *, 8 FROM orphan_gl_line
)
SELECT ledger_id,
       ledger_id || '-I' || ROW_NUMBER() OVER (PARTITION BY ledger_id
                                               ORDER BY rank, evidence_ids[1]) AS item_id,
       pattern,
       CAST(amount AS DECIMAL(18,2)) AS amount,
       evidence_ids
FROM all_items
ORDER BY ledger_id, rank, evidence_ids[1];

-- ---------------------------------------------------------------------------
-- Summary: what the candidates explain and what is left over
CREATE OR REPLACE TABLE recon_summary AS
SELECT b.ledger_id, b.sl_end, b.gl_end, b.difference,
       CAST(COALESCE(SUM(c.amount), 0) AS DECIMAL(18,2))                AS candidate_total,
       COUNT(c.item_id)                                                 AS candidate_count,
       CAST(b.difference - COALESCE(SUM(c.amount), 0) AS DECIMAL(18,2)) AS unexplained
FROM recon_balances b
LEFT JOIN recon_candidates c USING (ledger_id)
GROUP BY b.ledger_id, b.sl_end, b.gl_end, b.difference
ORDER BY b.ledger_id;
