-- =========================================================================
-- example_queries.sql — sample analytical queries against the loaded dataset
-- Spec references: 00-overview.md (business questions)
-- =========================================================================

-- Q1: What's the health of account X on date D?
--     (Change the WHERE clause to filter to a specific account_id / date.)
--     This is the daily AVR view — reuses the north_star_metric.sql logic.
--
--     For a per-day trend, wrap north_star_metric.sql in a UDF or run it in
--     a loop per date. For a single "as of today" snapshot, the north_star
--     query itself is sufficient.

-- Q2: What did each account BUY vs. CONSUME in the last complete month?
WITH last_month AS (
  SELECT
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AS m_start,
    LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AS m_end
),
consumed AS (
  SELECT u.account_id, SUM(u.compute_credits_consumed) AS consumed_credits
  FROM `global-customer-services-gcs.gcs_north_star.daily_usage_logs` u, last_month lm
  WHERE u.date BETWEEN lm.m_start AND lm.m_end
  GROUP BY u.account_id
),
committed AS (
  SELECT
    c.account_id,
    c.included_monthly_compute_credits AS included_credits,
    c.annual_commit_dollars
  FROM `global-customer-services-gcs.gcs_north_star.contracts` c, last_month lm
  WHERE lm.m_end BETWEEN c.start_date AND c.end_date
)
SELECT
  a.account_id,
  a.company_name,
  a.segment,
  cm.annual_commit_dollars,
  cm.included_credits AS purchased_monthly_credits,
  IFNULL(co.consumed_credits, 0) AS consumed_last_month,
  ROUND(SAFE_DIVIDE(IFNULL(co.consumed_credits, 0), cm.included_credits), 3) AS consumption_ratio
FROM `global-customer-services-gcs.gcs_north_star.accounts` a
JOIN committed cm USING (account_id)
LEFT JOIN consumed co USING (account_id)
ORDER BY consumption_ratio DESC
LIMIT 25;


-- Q3: Which accounts show the technical-health "danger zone"?
--     Latest health color = Red OR any open sev-1/2 ticket open more than 7 days.
SELECT
  a.account_id,
  a.company_name,
  a.segment,
  ah.health_color AS latest_health_color,
  COUNTIF(t.severity IN (1, 2) AND t.status IN ('Open','In Progress')) AS open_sev1_sev2,
  MAX(DATE_DIFF(CURRENT_DATE(), t.opened_date, DAY)) AS oldest_open_ticket_days
FROM `global-customer-services-gcs.gcs_north_star.accounts` a
LEFT JOIN `global-customer-services-gcs.gcs_north_star.account_health` ah
  ON a.account_id = ah.account_id
 AND ah.date = (
   SELECT MAX(date) FROM `global-customer-services-gcs.gcs_north_star.account_health` ah2
   WHERE ah2.account_id = a.account_id
 )
LEFT JOIN `global-customer-services-gcs.gcs_north_star.support_tickets` t
  ON a.account_id = t.account_id
 AND t.status IN ('Open','In Progress')
GROUP BY a.account_id, a.company_name, a.segment, ah.health_color
HAVING latest_health_color = 'Red' OR open_sev1_sev2 > 0
ORDER BY open_sev1_sev2 DESC, latest_health_color DESC
LIMIT 25;


-- Q4: Overall platform usage trend (weekly, all accounts)
SELECT
  DATE_TRUNC(date, WEEK(MONDAY)) AS week_start,
  COUNT(DISTINCT account_id) AS active_accounts,
  SUM(compute_credits_consumed) AS total_credits_consumed
FROM `global-customer-services-gcs.gcs_north_star.daily_usage_logs`
WHERE account_id IN (
  SELECT account_id FROM `global-customer-services-gcs.gcs_north_star.accounts`
)
GROUP BY week_start
ORDER BY week_start;


-- Q5: What does "good" look like? — AVR distribution across the book.
--     Requires the AVR metric result set from north_star_metric.sql, either
--     materialized to a table or wrapped in a CTE.
--
--     Suggested approach for phase 2: CREATE OR REPLACE TABLE
--     `gcs_north_star.avr_daily` PARTITION BY scoring_date AS (
--       -- entire north_star_metric.sql query --
--     );
--     then:
--     SELECT band, COUNT(*), AVG(avr_score) FROM avr_daily
--     WHERE scoring_date = CURRENT_DATE() GROUP BY band;
