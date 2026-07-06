-- test_csm_rollup_band_counts.sql
-- Verifies spec 07 invariant #2: n_green + n_yellow + n_red = n_accounts for
-- every (snapshot_date, csm_id) row.

SELECT
    snapshot_date,
    csm_id,
    n_accounts,
    n_green,
    n_yellow,
    n_red,
    n_green + n_yellow + n_red AS sum_bands
FROM {{ ref('mart_csm_avr') }}
WHERE n_green + n_yellow + n_red != n_accounts
