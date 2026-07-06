-- test_csm_rollup_account_counts.sql
-- Verifies spec 07 invariant #1: for each snapshot_date, sum of n_accounts
-- across CSMs in mart_csm_avr equals the count of distinct SCOREABLE accounts
-- with an active contract on that snapshot in mart_account_avr.
--
-- Ramp-period accounts (is_ramp_period = TRUE) are excluded from mart_csm_avr
-- aggregations entirely (see mart_csm_avr.sql WHERE clause), so the
-- account-side count must apply the same filter to match.

WITH csm_side AS (
    SELECT snapshot_date, SUM(n_accounts) AS csm_total
    FROM {{ ref('mart_csm_avr') }}
    GROUP BY 1
),

account_side AS (
    SELECT snapshot_date, COUNT(DISTINCT account_id) AS account_total
    FROM {{ ref('mart_account_avr') }}
    WHERE NOT is_ramp_period
    GROUP BY 1
)

SELECT
    c.snapshot_date,
    c.csm_total,
    a.account_total,
    c.csm_total - a.account_total AS delta
FROM csm_side c
JOIN account_side a USING (snapshot_date)
WHERE c.csm_total != a.account_total
