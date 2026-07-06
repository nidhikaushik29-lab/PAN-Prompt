-- stg_support_tickets.sql
-- Staging pass-through for support_tickets.
-- severity is INT64 (1=critical, 2=high, 3=low). Adds is_open convenience
-- flag so downstream models don't repeat the null/status logic.
-- Spec: 02-data-model.md#support_tickets

SELECT
    ticket_id,
    account_id,
    opened_date,
    closed_date,
    severity,
    product_area,
    status,
    (status IN ('Open', 'In Progress')) AS is_open
FROM {{ source('gcs_raw', 'support_tickets') }}
