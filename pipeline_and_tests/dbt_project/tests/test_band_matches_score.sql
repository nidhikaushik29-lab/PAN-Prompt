-- test_band_matches_score.sql
-- Fails if the band column is inconsistent with avr_score per spec 01:
--   Green      when avr_score >= 75
--   Yellow     when 50 <= avr_score < 75
--   Red        when avr_score < 50
--   Onboarding when is_ramp_period (avr_score IS NULL)

SELECT
    snapshot_date,
    account_id,
    avr_score,
    band,
    is_ramp_period
FROM {{ ref('mart_account_avr') }}
WHERE (avr_score >= 75                       AND band != 'Green')
   OR (avr_score >= 50 AND avr_score < 75    AND band != 'Yellow')
   OR (avr_score IS NOT NULL AND avr_score < 50 AND band != 'Red')
   OR (avr_score IS NULL AND band != 'Onboarding')
   OR (is_ramp_period AND band != 'Onboarding')
   OR (NOT is_ramp_period AND band = 'Onboarding')
