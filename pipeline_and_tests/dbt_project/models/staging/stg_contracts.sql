-- stg_contracts.sql
-- Staging pass-through for contracts.
-- Adds derived contract_days for downstream proration math.
-- Spec: 02-data-model.md#contracts

SELECT
    contract_id,
    account_id,
    start_date,
    end_date,
    DATE_DIFF(end_date, start_date, DAY) + 1     AS contract_days,
    annual_commit_dollars,
    included_monthly_compute_credits,
    contract_type
FROM {{ source('gcs_raw', 'contracts') }}
