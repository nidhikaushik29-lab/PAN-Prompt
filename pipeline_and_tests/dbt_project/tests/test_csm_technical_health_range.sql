-- test_csm_technical_health_range.sql
-- Fails if any mart_csm_avr row has avg_technical_health or
-- arr_weighted_technical_health outside [0, 100]. Both are derived from
-- t_score ∈ [0, 1] (guaranteed by mart_account_avr LEAST/GREATEST clamps)
-- and scaled ×100, so any violation indicates a rollup formula regression.
--
-- NULL is intentionally excluded: zero-book CSMs (n_accounts = 0) legitimately
-- have NULL for both columns and match the existing avg_avr / arr_weighted_avr
-- convention documented in models/marts/schema.yml.

SELECT
    snapshot_date,
    csm_id,
    n_accounts,
    avg_technical_health,
    arr_weighted_technical_health
FROM {{ ref('mart_csm_avr') }}
WHERE avg_technical_health          < 0 OR avg_technical_health          > 100
   OR arr_weighted_technical_health < 0 OR arr_weighted_technical_health > 100
