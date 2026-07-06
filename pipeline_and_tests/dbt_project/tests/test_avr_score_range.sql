-- test_avr_score_range.sql
-- Fails if any mart_account_avr row has avr_score outside [0, 100] or if any
-- component score is outside [0, 1]. Bounds are guaranteed by the metric SQL
-- (LEAST/GREATEST clamps), so any violation indicates a formula regression.
--
-- Ramp-period accounts have avr_score = NULL by design (see spec 01 § Known
-- limitations); excluded from the range check via IS NOT NULL guard. Component
-- scores are still populated for audit purposes even during ramp, so those
-- bounds continue to be enforced.

SELECT
    snapshot_date,
    account_id,
    avr_score,
    d_score,
    c_score,
    t_score,
    r_score,
    b_score
FROM {{ ref('mart_account_avr') }}
WHERE (avr_score IS NOT NULL AND (avr_score < 0 OR avr_score > 100))
   OR d_score  < 0 OR d_score  > 1
   OR c_score  < 0 OR c_score  > 1
   OR t_score  < 0 OR t_score  > 1
   OR r_score  < 0 OR r_score  > 1
   OR b_score  < 0 OR b_score  > 1
