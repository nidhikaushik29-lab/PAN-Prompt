-- test_ticket_closed_after_opened.sql
-- Fails if closed_date < opened_date. Basic causality check.

SELECT
    ticket_id,
    opened_date,
    closed_date
FROM {{ ref('stg_support_tickets') }}
WHERE closed_date IS NOT NULL
  AND closed_date < opened_date
