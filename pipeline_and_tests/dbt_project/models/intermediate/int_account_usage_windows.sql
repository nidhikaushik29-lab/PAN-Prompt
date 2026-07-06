-- int_account_usage_windows.sql
-- Filters usage logs to (a) rows with a real account_id and (b) rows that
-- fall inside an active contract window on some snapshot_date.
--
-- Edge cases handled by inner joins:
--   #5a (orphaned usage): dropped by JOIN stg_accounts
--   #5b (out-of-window usage): dropped by BETWEEN start_date AND end_date
--
-- The join to int_account_contract_active is on the contract window itself,
-- NOT on a snapshot_date. This gives us "all usage rows that belong to SOME
-- active contract" — the marts then filter to trailing windows per snapshot.
--
-- Grain: one row per (log_id). log_id is preserved as PK.
--
-- Spec: 01-north-star-metric.md § Edge-case handling rows 5a, 5b

WITH usage AS (
    SELECT
        u.log_id,
        u.account_id,
        u.date,
        u.compute_credits_consumed
    FROM {{ ref('stg_daily_usage_logs') }} u
    -- Drop orphaned rows (account_id not in accounts)
    INNER JOIN {{ ref('stg_accounts') }} a USING (account_id)
),

usage_in_any_contract AS (
    -- A usage row is "in-window" if it falls inside ANY contract for that
    -- account (not just the one active on a scoring date). This preserves
    -- history for trailing-window calculations.
    SELECT DISTINCT
        u.log_id,
        u.account_id,
        u.date,
        u.compute_credits_consumed
    FROM usage u
    INNER JOIN {{ ref('stg_contracts') }} c
      ON u.account_id = c.account_id
     AND u.date BETWEEN c.start_date AND c.end_date
)

SELECT * FROM usage_in_any_contract
