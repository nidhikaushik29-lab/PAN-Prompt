-- stg_account_health.sql
-- Staging pass-through for account_health.
-- Grain: weekly (Sundays). health_color ∈ {Green, Yellow, Red}.
-- Spec: 02-data-model.md#account_health

SELECT
    account_id,
    date,
    health_color,
    compute_credits_consumed AS weekly_credits_consumed
FROM {{ source('gcs_raw', 'account_health') }}
