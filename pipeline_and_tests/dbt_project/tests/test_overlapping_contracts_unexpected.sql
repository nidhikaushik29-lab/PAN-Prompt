-- test_overlapping_contracts_unexpected.sql
-- Fails if TWO contracts overlap in time for the same account AND both are of
-- the SAME type.
--
-- Expected overlap patterns:
--   * New   x Renewal    — customer signs the next-year contract up to ~15d
--                          before the current one expires (see contracts.py:84
--                          + specs/02-data-model.md#contracts-overlap-rules)
--   * New   x Expansion  — mid-year expansion (edge case #4)
--   * Renewal x Expansion — expansion in a renewal window
--
-- UNEXPECTED overlap: same contract_type on both sides (New/New, Renewal/
-- Renewal, or Expansion/Expansion). That indicates a data pipeline bug —
-- double-write, incorrect renewal date, or bad expansion injection.

WITH pairs AS (
    SELECT
        c1.account_id,
        c1.contract_id      AS contract_a,
        c2.contract_id      AS contract_b,
        c1.contract_type    AS type_a,
        c2.contract_type    AS type_b,
        c1.start_date       AS start_a,
        c1.end_date         AS end_a,
        c2.start_date       AS start_b,
        c2.end_date         AS end_b
    FROM {{ ref('stg_contracts') }} c1
    JOIN {{ ref('stg_contracts') }} c2
      ON c1.account_id  = c2.account_id
     AND c1.contract_id < c2.contract_id            -- avoid dup pairs
     AND c1.start_date <= c2.end_date               -- overlap
     AND c2.start_date <= c1.end_date
)

SELECT *
FROM pairs
WHERE type_a = type_b
