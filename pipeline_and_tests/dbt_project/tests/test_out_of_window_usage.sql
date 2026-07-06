-- test_out_of_window_usage.sql
-- Fails if usage log rows fall outside ANY contract window for their account.
--
-- SYNTHETIC-DATA NOTE: seed injects ~100 out-of-window rows (edge case #5b:
-- 50 rows pre-contract, 50 rows post-contract). Kept as severity=warn.

{{ config(severity='warn') }}

WITH usage AS (
    SELECT u.log_id, u.account_id, u.date
    FROM {{ ref('stg_daily_usage_logs') }} u
    -- Only rows with a valid account_id — orphans are handled by a separate test
    INNER JOIN {{ ref('stg_accounts') }} a USING (account_id)
),

any_contract_covers AS (
    SELECT
        u.log_id,
        u.account_id,
        u.date,
        LOGICAL_OR(u.date BETWEEN c.start_date AND c.end_date) AS covered
    FROM usage u
    LEFT JOIN {{ ref('stg_contracts') }} c
      ON u.account_id = c.account_id
    GROUP BY 1, 2, 3
)

SELECT log_id, account_id, date
FROM any_contract_covers
WHERE NOT covered
