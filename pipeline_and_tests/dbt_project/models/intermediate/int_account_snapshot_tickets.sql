-- int_account_snapshot_tickets.sql
-- Ticket signals for the T (Technical Health) component of AVR.
--
-- Grain: (snapshot_date, account_id) — DENSE across all ever-active accounts,
--        so LAG for the 30-day trend signal has continuous history even for
--        months in which an account has zero open tickets. (Prior to
--        2026-07-04 this model was sparse and only exposed sev-1/sev-2 open
--        counts; rewritten to power the enhanced T formula per exec ask —
--        see specs/01-north-star-metric.md § T component.)
--
-- An "open ticket as of snapshot_date" satisfies BOTH:
--   opened_date <= snapshot_date
--   (closed_date IS NULL OR closed_date > snapshot_date)
--
-- Columns:
--   open_sev1, open_sev2, open_sev3   raw counts of open tickets by severity
--   age_weighted_load                 SUM over open tickets of
--                                       sev_weight × age_multiplier
--                                     where:
--                                       sev_weight     = {1: 0.50, 2: 0.20, 3: 0.05}
--                                       age_multiplier = 1 + LEAST(1, age_days/30)
--                                                        (1× fresh, 2× at ≥30 days)
--   prev_age_weighted_load            age_weighted_load from the previous
--                                     snapshot (via LAG over account_id).
--                                     NULL only for the very first snapshot
--                                     in the window; mart falls back to
--                                     current value → T_trend = 0.5 (neutral).

WITH open_tickets AS (
    SELECT
        s.snapshot_date,
        t.account_id,
        t.severity,
        DATE_DIFF(s.snapshot_date, t.opened_date, DAY) AS age_days
    FROM {{ ref('int_snapshot_dates') }} s
    JOIN {{ ref('stg_support_tickets') }} t
      ON t.opened_date <= s.snapshot_date
     AND (t.closed_date IS NULL OR t.closed_date > s.snapshot_date)
),

per_snapshot_account AS (
    SELECT
        snapshot_date,
        account_id,
        COUNTIF(severity = 1) AS open_sev1,
        COUNTIF(severity = 2) AS open_sev2,
        COUNTIF(severity = 3) AS open_sev3,
        SUM(
            CASE severity
                WHEN 1 THEN 0.50
                WHEN 2 THEN 0.20
                WHEN 3 THEN 0.05
                ELSE 0.00
            END
            * (1.0 + LEAST(1.0, CAST(age_days AS FLOAT64) / 30.0))
        ) AS age_weighted_load
    FROM open_tickets
    GROUP BY 1, 2
),

-- Dense (snapshot × account) grid so LAG for the trend signal has continuous
-- history even in months with zero open tickets. Scope to accounts that
-- appear in int_account_contract_active (i.e. are ever active in the window)
-- so we don't over-inflate cardinality with accounts that never transact.
grid AS (
    SELECT
        s.snapshot_date,
        a.account_id
    FROM {{ ref('int_snapshot_dates') }} s
    CROSS JOIN (
        SELECT DISTINCT account_id
        FROM {{ ref('int_account_contract_active') }}
    ) a
),

dense AS (
    SELECT
        g.snapshot_date,
        g.account_id,
        COALESCE(p.open_sev1, 0)           AS open_sev1,
        COALESCE(p.open_sev2, 0)           AS open_sev2,
        COALESCE(p.open_sev3, 0)           AS open_sev3,
        COALESCE(p.age_weighted_load, 0.0) AS age_weighted_load
    FROM grid g
    LEFT JOIN per_snapshot_account p USING (snapshot_date, account_id)
)

SELECT
    snapshot_date,
    account_id,
    open_sev1,
    open_sev2,
    open_sev3,
    age_weighted_load,
    LAG(age_weighted_load) OVER (
        PARTITION BY account_id ORDER BY snapshot_date
    ) AS prev_age_weighted_load
FROM dense
