-- test_orphaned_usage.sql
-- Fails if usage log rows reference an account_id that doesn't exist in the
-- accounts table.
--
-- SYNTHETIC-DATA NOTE: our seed data intentionally injects ~200 orphaned
-- rows (edge case #5a in specs/04-edge-cases.md). We keep the test as
-- severity=warn so dbt surfaces the count in the run output without failing
-- the entire build. In a real deployment against clean data, flip to
-- severity=error.

{{ config(severity='warn') }}

SELECT
    u.log_id,
    u.account_id,
    u.date,
    u.compute_credits_consumed
FROM {{ ref('stg_daily_usage_logs') }} u
LEFT JOIN {{ ref('stg_accounts') }}    a USING (account_id)
WHERE a.account_id IS NULL
