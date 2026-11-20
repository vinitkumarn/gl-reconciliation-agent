-- load.sql: read each CSV as text, CAST to real types. Money is DECIMAL(18,2). No dedupe.
-- Python replaces __CSV_DIR__ with the CSV folder before running this file.

CREATE OR REPLACE TABLE sla_headers AS
SELECT CAST(ae_header_id AS BIGINT)            AS ae_header_id,
       ledger_id,
       CAST(accounting_date AS DATE)           AS accounting_date,
       period_name,
       gl_transfer_status_code,
       CAST(supplier_id AS BIGINT)             AS supplier_id
FROM read_csv('__CSV_DIR__/sla_headers.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE sla_lines AS
SELECT CAST(ae_header_id AS BIGINT)            AS ae_header_id,
       CAST(ae_line_num AS INTEGER)            AS ae_line_num,
       account,
       accounting_class,
       CAST(accounted_dr AS DECIMAL(18,2))     AS accounted_dr,
       CAST(accounted_cr AS DECIMAL(18,2))     AS accounted_cr,
       CAST(NULLIF(gl_sl_link_id, '') AS BIGINT) AS gl_sl_link_id,
       description
FROM read_csv('__CSV_DIR__/sla_lines.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE sla_control_balances AS
SELECT ledger_id,
       account,
       CAST(supplier_id AS BIGINT)             AS supplier_id,
       period_name,
       CAST(begin_balance_dr AS DECIMAL(18,2)) AS begin_balance_dr,
       CAST(begin_balance_cr AS DECIMAL(18,2)) AS begin_balance_cr
FROM read_csv('__CSV_DIR__/sla_control_balances.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE gl_je_headers AS
SELECT CAST(je_header_id AS BIGINT)            AS je_header_id,
       ledger_id,
       je_source,
       period_name,
       status,
       NULLIF(import_ref, '')                  AS import_ref,
       NULLIF(accrual_rev_period, '')          AS accrual_rev_period,
       NULLIF(accrual_rev_status, '')          AS accrual_rev_status,
       description
FROM read_csv('__CSV_DIR__/gl_je_headers.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE gl_je_lines AS
SELECT CAST(je_header_id AS BIGINT)            AS je_header_id,
       CAST(je_line_num AS INTEGER)            AS je_line_num,
       account,
       CAST(accounted_dr AS DECIMAL(18,2))     AS accounted_dr,
       CAST(accounted_cr AS DECIMAL(18,2))     AS accounted_cr,
       CAST(NULLIF(gl_sl_link_id, '') AS BIGINT) AS gl_sl_link_id
FROM read_csv('__CSV_DIR__/gl_je_lines.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE gl_balances AS
SELECT ledger_id,
       account,
       period_name,
       CAST(begin_balance_dr AS DECIMAL(18,2)) AS begin_balance_dr,
       CAST(begin_balance_cr AS DECIMAL(18,2)) AS begin_balance_cr,
       CAST(period_net_dr AS DECIMAL(18,2))    AS period_net_dr,
       CAST(period_net_cr AS DECIMAL(18,2))    AS period_net_cr
FROM read_csv('__CSV_DIR__/gl_balances.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE periods AS
SELECT ledger_id,
       period_name,
       status,
       CAST(start_date AS DATE)                AS start_date,
       CAST(end_date AS DATE)                  AS end_date
FROM read_csv('__CSV_DIR__/periods.csv', all_varchar = true, header = true);

CREATE OR REPLACE TABLE suppliers AS
SELECT CAST(supplier_id AS BIGINT)             AS supplier_id,
       supplier_name
FROM read_csv('__CSV_DIR__/suppliers.csv', all_varchar = true, header = true);

-- ---------------------------------------------------------------------------
-- The 3 data checks. Each view must return 0 rows; Python fails loudly otherwise.

-- Check 1: every journal balances (Dr = Cr), in the subledger and in the GL.
CREATE OR REPLACE VIEW check_journals_balance AS
SELECT 'AE:' || ae_header_id AS journal, SUM(accounted_dr) AS dr, SUM(accounted_cr) AS cr
FROM sla_lines GROUP BY ae_header_id
HAVING SUM(accounted_dr) <> SUM(accounted_cr)
UNION ALL
SELECT 'JE:' || je_header_id, SUM(accounted_dr), SUM(accounted_cr)
FROM gl_je_lines GROUP BY je_header_id
HAVING SUM(accounted_dr) <> SUM(accounted_cr);

-- Check 2: every period used anywhere is a valid period of that ledger.
CREATE OR REPLACE VIEW check_valid_periods AS
WITH used AS (
    SELECT 'sla_headers' AS tbl, ledger_id, period_name FROM sla_headers
    UNION ALL SELECT 'gl_je_headers', ledger_id, period_name FROM gl_je_headers
    UNION ALL SELECT 'gl_je_headers.accrual_rev_period', ledger_id, accrual_rev_period
              FROM gl_je_headers WHERE accrual_rev_period IS NOT NULL
    UNION ALL SELECT 'gl_balances', ledger_id, period_name FROM gl_balances
    UNION ALL SELECT 'sla_control_balances', ledger_id, period_name FROM sla_control_balances
)
SELECT DISTINCT u.tbl, u.ledger_id, u.period_name
FROM used u
WHERE NOT EXISTS (SELECT 1 FROM periods p
                  WHERE p.ledger_id = u.ledger_id AND p.period_name = u.period_name);

-- Check 3: GL_BALANCES period net equals the posted journal lines.
CREATE OR REPLACE VIEW check_gl_balances_tie AS
WITH net AS (
    SELECT h.ledger_id, l.account, h.period_name,
           SUM(l.accounted_dr) AS dr, SUM(l.accounted_cr) AS cr
    FROM gl_je_lines l JOIN gl_je_headers h USING (je_header_id)
    WHERE h.status = 'P'
    GROUP BY h.ledger_id, l.account, h.period_name
)
SELECT COALESCE(b.ledger_id, n.ledger_id)     AS ledger_id,
       COALESCE(b.account, n.account)         AS account,
       COALESCE(b.period_name, n.period_name) AS period_name,
       b.period_net_dr, n.dr AS journal_dr, b.period_net_cr, n.cr AS journal_cr
FROM gl_balances b
FULL OUTER JOIN net n
  ON b.ledger_id = n.ledger_id AND b.account = n.account AND b.period_name = n.period_name
WHERE COALESCE(b.period_net_dr, 0) <> COALESCE(n.dr, 0)
   OR COALESCE(b.period_net_cr, 0) <> COALESCE(n.cr, 0);
