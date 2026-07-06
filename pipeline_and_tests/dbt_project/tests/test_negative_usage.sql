-- test_negative_usage.sql
-- Fails if any usage log row has negative compute_credits_consumed.
-- Negative usage is physically impossible in this domain (customers cannot
-- "un-consume" compute).

SELECT
    log_id,
    account_id,
    date,
    compute_credits_consumed
FROM {{ ref('stg_daily_usage_logs') }}
WHERE compute_credits_consumed < 0
