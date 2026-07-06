-- test_ramp_accounts_have_null_avr.sql
-- Fails if any ramp-period account has a populated avr_score OR any non-ramp
-- account has NULL avr_score. Enforces the v1 design decision that
-- onboarding accounts (days_in_contract < ramp_period_days) are deliberately
-- not scored — see specs/01-north-star-metric.md § Known limitations and the
-- assembled CTE in mart_account_avr.sql.

SELECT
    snapshot_date,
    account_id,
    is_ramp_period,
    avr_score,
    band
FROM {{ ref('mart_account_avr') }}
WHERE (is_ramp_period       AND avr_score IS NOT NULL)
   OR (is_ramp_period       AND band != 'Onboarding')
   OR (NOT is_ramp_period   AND avr_score IS NULL)
   OR (NOT is_ramp_period   AND band = 'Onboarding')
