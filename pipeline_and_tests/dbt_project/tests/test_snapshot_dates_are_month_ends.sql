-- test_snapshot_dates_are_month_ends.sql
-- Verifies int_snapshot_dates only contains month-end dates. Regressions in
-- the date generator (e.g., off-by-one in LAST_DAY) would produce mid-month
-- snapshots and silently skew every trailing-window aggregation.

SELECT snapshot_date
FROM {{ ref('int_snapshot_dates') }}
WHERE snapshot_date != LAST_DAY(snapshot_date, MONTH)
