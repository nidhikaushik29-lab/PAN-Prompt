-- test_contract_start_before_end.sql
-- Fails if any contract has start_date >= end_date. Zero-length or negative
-- contracts break every downstream aggregation.

SELECT
    contract_id,
    account_id,
    start_date,
    end_date
FROM {{ ref('stg_contracts') }}
WHERE start_date >= end_date
