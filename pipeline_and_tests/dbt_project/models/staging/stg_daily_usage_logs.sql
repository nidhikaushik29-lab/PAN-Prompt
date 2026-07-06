-- stg_daily_usage_logs.sql
-- Staging pass-through for daily_usage_logs.
--
-- IMPORTANT: this model does NOT filter orphaned or out-of-window rows.
-- Filtering happens downstream in int_account_usage_windows so that data-
-- quality tests (tests/test_orphaned_usage.sql,
-- tests/test_out_of_window_usage.sql) can still surface them.
--
-- Spec: 02-data-model.md#daily_usage_logs, 04-edge-cases.md#5

SELECT
    log_id,
    account_id,
    date,
    compute_credits_consumed
FROM {{ source('gcs_raw', 'daily_usage_logs') }}
