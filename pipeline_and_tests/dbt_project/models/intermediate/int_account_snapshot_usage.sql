-- int_account_snapshot_usage.sql
-- Rolls trailing usage windows up to (snapshot_date, account_id) grain.
-- Computes all consumption inputs the AVR components need in one pass.
--
-- Outputs (per snapshot_date, account_id):
--   credits_last_month     for D component (deployment depth)
--   mean_90d, sd_90d, n_days_90d  for C component (consumption sustainability)
--   credits_last_3mo       for Expansion Opportunity flag
--   credits_ytd_contract   for B component (bookings realization)
--
-- Bounds explanation:
--   "last month" = full calendar month preceding snapshot_date
--   "90d" = snapshot_date - 90 days .. snapshot_date (inclusive)
--   "3mo" = same as 90d (used for expansion flag)
--   "ytd_contract" = active contract start_date .. snapshot_date
--
-- Depends on: int_snapshot_dates, int_account_contract_active,
--             int_account_usage_windows

WITH snapshots AS (
    SELECT snapshot_date FROM {{ ref('int_snapshot_dates') }}
),

active AS (
    SELECT snapshot_date, account_id, start_date
    FROM {{ ref('int_account_contract_active') }}
),

usage AS (
    SELECT account_id, date, compute_credits_consumed
    FROM {{ ref('int_account_usage_windows') }}
),

-- Bounds for each snapshot
snap_bounds AS (
    SELECT
        snapshot_date,
        DATE_TRUNC(DATE_SUB(snapshot_date, INTERVAL 1 MONTH), MONTH) AS last_month_start,
        LAST_DAY(DATE_SUB(snapshot_date, INTERVAL 1 MONTH), MONTH)   AS last_month_end,
        DATE_SUB(snapshot_date, INTERVAL {{ var("cv_window_days") }} DAY) AS window_90d_start
    FROM snapshots
),

usage_by_snapshot AS (
    SELECT
        b.snapshot_date,
        a.account_id,
        a.start_date AS contract_start,
        -- Deployment Depth: last complete calendar month
        SUM(IF(u.date BETWEEN b.last_month_start AND b.last_month_end,
               u.compute_credits_consumed, 0))                     AS credits_last_month,
        -- Consumption Sustainability: trailing 90d stats
        AVG(IF(u.date BETWEEN b.window_90d_start AND b.snapshot_date,
               u.compute_credits_consumed, NULL))                  AS mean_90d,
        STDDEV(IF(u.date BETWEEN b.window_90d_start AND b.snapshot_date,
               u.compute_credits_consumed, NULL))                  AS sd_90d,
        COUNTIF(u.date BETWEEN b.window_90d_start AND b.snapshot_date
                AND u.compute_credits_consumed IS NOT NULL)        AS n_days_90d,
        -- Expansion flag: same window as CV
        SUM(IF(u.date BETWEEN b.window_90d_start AND b.snapshot_date,
               u.compute_credits_consumed, 0))                     AS credits_last_3mo,
        -- Bookings Realization: usage from active-contract start through snapshot
        SUM(IF(u.date BETWEEN a.start_date AND b.snapshot_date,
               u.compute_credits_consumed, 0))                     AS credits_ytd_contract
    FROM snap_bounds b
    JOIN active     a  ON a.snapshot_date = b.snapshot_date
    LEFT JOIN usage u  ON u.account_id    = a.account_id
                       AND u.date BETWEEN a.start_date AND b.snapshot_date  -- only within active contract span
    GROUP BY 1, 2, 3
)

SELECT * FROM usage_by_snapshot
