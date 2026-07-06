-- stg_csm_reps.sql
-- Staging pass-through for csm_reps. No business logic; just type-safe rename.
-- Spec: 02-data-model.md#csm_reps

SELECT
    csm_id,
    name           AS csm_name,
    region,
    segment        AS csm_segment,
    hire_date
FROM {{ source('gcs_raw', 'csm_reps') }}
