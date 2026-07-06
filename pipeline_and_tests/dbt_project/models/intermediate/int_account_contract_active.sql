-- int_account_contract_active.sql
-- For each (snapshot_date, account_id), pick the *active* contract.
--
-- Grain: (snapshot_date, account_id) — one row max. Only accounts with an
-- active contract on the snapshot_date appear here.
--
-- Edge case #4 (mid-year expansions): when two contracts overlap, pick the
-- one with the LATEST start_date. The expansion contract (with the larger
-- monthly credit allotment) becomes the denominator for D and B in AVR.
--
-- Spec: 01-north-star-metric.md § Edge-case handling row 4

WITH candidates AS (
    SELECT
        s.snapshot_date,
        c.account_id,
        c.contract_id,
        c.start_date,
        c.end_date,
        c.contract_days,
        c.annual_commit_dollars,
        c.included_monthly_compute_credits,
        c.contract_type,
        DATE_DIFF(c.end_date, s.snapshot_date, DAY) AS days_to_renewal,
        DATE_DIFF(s.snapshot_date, c.start_date, DAY) + 1 AS days_in_contract,
        ROW_NUMBER() OVER (
            PARTITION BY s.snapshot_date, c.account_id
            ORDER BY c.start_date DESC
        ) AS rn
    FROM {{ ref('int_snapshot_dates') }} s
    JOIN {{ ref('stg_contracts') }}     c
      ON s.snapshot_date BETWEEN c.start_date AND c.end_date
)

SELECT * EXCEPT(rn)
FROM candidates
WHERE rn = 1
