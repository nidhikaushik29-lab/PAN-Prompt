-- int_snapshot_dates.sql
-- Generates the set of scoring dates for the AVR time series.
-- One row per month-end from vars.snapshot_start to vars.snapshot_end.
-- 18 rows for the default window (2025-01-31 through 2026-06-30).
--
-- Used by:
--   int_account_contract_active  (which contracts are active on each date)
--   mart_account_avr             (fan out scoring per date)
--
-- Why month-end and not daily: 1000 accounts × 550 days = 550k rows and lots
-- of trailing-90d recomputation. Monthly snapshots give a usable time series
-- for dashboards at ~11k rows.

WITH date_series AS (
    SELECT
        LAST_DAY(month_first, MONTH) AS snapshot_date
    FROM UNNEST(
        GENERATE_DATE_ARRAY(
            DATE_TRUNC(DATE '{{ var("snapshot_start") }}', MONTH),
            DATE_TRUNC(DATE '{{ var("snapshot_end") }}',   MONTH),
            INTERVAL 1 MONTH
        )
    ) AS month_first
)

SELECT snapshot_date
FROM date_series
ORDER BY snapshot_date
