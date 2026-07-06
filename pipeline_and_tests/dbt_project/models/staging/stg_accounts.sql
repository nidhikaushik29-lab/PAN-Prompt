-- stg_accounts.sql
-- Staging pass-through for accounts.
-- FK note: rep_id → csm_reps.csm_id (name mismatch is intentional; see
-- specs/02-data-model.md § "Column naming decision").
-- Spec: 02-data-model.md#accounts

SELECT
    account_id,
    company_name,
    industry,
    rep_id,
    segment           AS account_segment,
    signup_date
FROM {{ source('gcs_raw', 'accounts') }}
