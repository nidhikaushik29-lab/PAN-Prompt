-- =========================================================================
-- north_star_metric.sql
-- Account Value Realization (AVR) — GCS North Star metric
-- Spec reference: specs/01-north-star-metric.md
--
-- AVR = 100 * (0.20*D + 0.30*C + 0.25*T + 0.15*R + 0.10*B)
--   D  Deployment Depth        (last-month consumption vs allotment, capped 1.0)
--   C  Consumption Sustainability (1 - CV of daily usage last 90d)
--   T  Technical Health        (blend of health_color + open sev-1/2 load)
--   R  Retention Signal        (proximity-to-renewal × health of last 30d)
--   B  Bookings Realization    (YTD consumed vs prorated commit, capped 1.0)
--
-- Grain: one row per (account_id) on the scoring date @scoring_date.
-- Default scoring_date = the max date in daily_usage_logs (i.e., "today"
-- for the synthetic dataset). run_metric.py overrides via query parameter.
-- =========================================================================

-- Scoring date defaults to 2026-01-31 (13 months into the data window, when
-- ~640 contracts are active — much richer signal than at WINDOW_END where
-- most contracts have expired). run_metric.py overrides via @scoring_date
-- query parameter.
DECLARE scoring_date DATE DEFAULT DATE '2026-01-31';

WITH
-- Filter usage to real accounts only (drops orphans from edge case #5a)
clean_usage AS (
  SELECT u.account_id, u.date, u.compute_credits_consumed
  FROM `global-customer-services-gcs.gcs_north_star.daily_usage_logs` u
  INNER JOIN `global-customer-services-gcs.gcs_north_star.accounts` a
    ON u.account_id = a.account_id
),

-- Pick the "active" contract for each account as of scoring_date.
-- If multiple contracts overlap (edge case #4), pick the one with the
-- latest start_date (i.e., the expansion contract wins).
active_contract AS (
  SELECT
    account_id,
    contract_id,
    start_date,
    end_date,
    annual_commit_dollars,
    included_monthly_compute_credits,
    contract_type,
    DATE_DIFF(end_date, scoring_date, DAY) AS days_to_renewal
  FROM (
    SELECT
      c.*,
      ROW_NUMBER() OVER (
        PARTITION BY account_id
        ORDER BY start_date DESC
      ) AS rn
    FROM `global-customer-services-gcs.gcs_north_star.contracts` c
    WHERE scoring_date BETWEEN c.start_date AND c.end_date
  )
  WHERE rn = 1
),

-- Filter usage to within active-contract windows (drops out-of-window rogue
-- logs from edge case #5b)
usage_in_window AS (
  SELECT u.account_id, u.date, u.compute_credits_consumed
  FROM clean_usage u
  INNER JOIN active_contract ac
    ON u.account_id = ac.account_id
   AND u.date BETWEEN ac.start_date AND ac.end_date
),

-- ============ D: Deployment Depth ============
-- Last full calendar month before scoring_date
last_month_bounds AS (
  SELECT
    DATE_TRUNC(DATE_SUB(scoring_date, INTERVAL 1 MONTH), MONTH) AS m_start,
    LAST_DAY(DATE_SUB(scoring_date, INTERVAL 1 MONTH), MONTH) AS m_end
),
last_month_usage AS (
  SELECT
    u.account_id,
    SUM(u.compute_credits_consumed) AS credits_last_month
  FROM usage_in_window u, last_month_bounds b
  WHERE u.date BETWEEN b.m_start AND b.m_end
  GROUP BY u.account_id
),
component_d AS (
  SELECT
    ac.account_id,
    LEAST(1.0, IFNULL(SAFE_DIVIDE(
      lmu.credits_last_month,
      ac.included_monthly_compute_credits
    ), 0)) AS d_score
  FROM active_contract ac
  LEFT JOIN last_month_usage lmu USING (account_id)
),

-- ============ C: Consumption Sustainability ============
-- 1 - coefficient_of_variation over the trailing 90 days
last_90d_stats AS (
  SELECT
    account_id,
    AVG(compute_credits_consumed)    AS mean_90d,
    STDDEV(compute_credits_consumed) AS sd_90d,
    COUNT(*)                          AS n_days_90d
  FROM usage_in_window
  WHERE date BETWEEN DATE_SUB(scoring_date, INTERVAL 90 DAY) AND scoring_date
  GROUP BY account_id
),
component_c AS (
  SELECT
    ac.account_id,
    -- If mean is 0 or fewer than 10 days of data, treat C as 0
    CASE
      WHEN s.mean_90d IS NULL OR s.mean_90d = 0 OR s.n_days_90d < 10 THEN 0.0
      ELSE GREATEST(0.0, LEAST(1.0, 1.0 - SAFE_DIVIDE(s.sd_90d, s.mean_90d)))
    END AS c_score
  FROM active_contract ac
  LEFT JOIN last_90d_stats s USING (account_id)
),

-- ============ T: Technical Health ============
-- Blend of latest health_color and open sev-1/2 ticket load as of scoring_date
latest_color AS (
  SELECT
    account_id,
    ARRAY_AGG(health_color ORDER BY date DESC LIMIT 1)[OFFSET(0)] AS latest_color
  FROM `global-customer-services-gcs.gcs_north_star.account_health`
  WHERE date <= scoring_date
  GROUP BY account_id
),
open_tickets AS (
  SELECT
    account_id,
    COUNTIF(severity = 1 AND (closed_date IS NULL OR closed_date > scoring_date)) AS open_sev1,
    COUNTIF(severity = 2 AND (closed_date IS NULL OR closed_date > scoring_date)) AS open_sev2
  FROM `global-customer-services-gcs.gcs_north_star.support_tickets`
  WHERE opened_date <= scoring_date
  GROUP BY account_id
),
component_t AS (
  SELECT
    ac.account_id,
    -- T_color: Green=1.0, Yellow=0.5, Red=0.0, missing=0.5
    (
      0.6 * CASE lc.latest_color
              WHEN 'Green'  THEN 1.0
              WHEN 'Yellow' THEN 0.5
              WHEN 'Red'    THEN 0.0
              ELSE                 0.5
            END
      + 0.4 * (1.0 - LEAST(1.0, (IFNULL(ot.open_sev1,0)*0.5 + IFNULL(ot.open_sev2,0)*0.2) / 3.0))
    ) AS t_score,
    IFNULL(ot.open_sev1, 0) AS open_sev1,
    IFNULL(ot.open_sev2, 0) AS open_sev2,
    lc.latest_color
  FROM active_contract ac
  LEFT JOIN latest_color lc USING (account_id)
  LEFT JOIN open_tickets ot USING (account_id)
),

-- ============ R: Retention Signal ============
red_in_last_30d AS (
  SELECT
    account_id,
    LOGICAL_OR(health_color = 'Red') AS had_red_30d
  FROM `global-customer-services-gcs.gcs_north_star.account_health`
  WHERE date BETWEEN DATE_SUB(scoring_date, INTERVAL 30 DAY) AND scoring_date
  GROUP BY account_id
),
component_r AS (
  SELECT
    ac.account_id,
    ac.days_to_renewal,
    CASE
      WHEN ac.days_to_renewal > 180 THEN 1.0
      WHEN ac.days_to_renewal BETWEEN 60 AND 180 THEN 0.75
      WHEN ac.days_to_renewal BETWEEN 0 AND 59
           AND NOT IFNULL(r.had_red_30d, FALSE) THEN 1.0
      WHEN ac.days_to_renewal BETWEEN 0 AND 59
           AND IFNULL(r.had_red_30d, FALSE) THEN 0.25
      ELSE 0.0
    END AS r_score
  FROM active_contract ac
  LEFT JOIN red_in_last_30d r USING (account_id)
),

-- ============ B: Bookings Realization ============
-- YTD-in-contract consumption vs prorated monthly allotment
ytd_usage AS (
  SELECT
    u.account_id,
    SUM(u.compute_credits_consumed) AS credits_ytd,
    -- Days elapsed in current contract
    DATE_DIFF(scoring_date, ac.start_date, DAY) + 1 AS days_in_contract
  FROM usage_in_window u
  JOIN active_contract ac USING (account_id)
  WHERE u.date >= ac.start_date AND u.date <= scoring_date
  GROUP BY u.account_id, ac.start_date
),
component_b AS (
  SELECT
    ac.account_id,
    LEAST(1.0, IFNULL(SAFE_DIVIDE(
      y.credits_ytd,
      ac.included_monthly_compute_credits * (y.days_in_contract / 30.0)
    ), 0)) AS b_score
  FROM active_contract ac
  LEFT JOIN ytd_usage y USING (account_id)
),

-- ============ Expansion Opportunity Flag ============
last_3mo_usage AS (
  SELECT
    account_id,
    SUM(compute_credits_consumed) AS credits_3mo
  FROM usage_in_window
  WHERE date BETWEEN DATE_SUB(scoring_date, INTERVAL 90 DAY) AND scoring_date
  GROUP BY account_id
),
expansion_flag_cte AS (
  SELECT
    ac.account_id,
    (
      IFNULL(l3.credits_3mo, 0) > 1.20 * (3 * ac.included_monthly_compute_credits)
      AND ac.days_to_renewal <= 180
    ) AS expansion_flag
  FROM active_contract ac
  LEFT JOIN last_3mo_usage l3 USING (account_id)
),

-- ============ Assemble AVR ============
avr AS (
  SELECT
    a.account_id,
    a.company_name,
    a.industry,
    a.segment,
    ac.contract_id,
    ac.contract_type,
    ac.annual_commit_dollars,
    ac.included_monthly_compute_credits,
    ac.days_to_renewal,
    d.d_score,
    c.c_score,
    t.t_score,
    r.r_score,
    b.b_score,
    t.open_sev1,
    t.open_sev2,
    t.latest_color,
    ROUND(100 * (
      0.20 * d.d_score
      + 0.30 * c.c_score
      + 0.25 * t.t_score
      + 0.15 * r.r_score
      + 0.10 * b.b_score
    ), 1) AS avr_score,
    ef.expansion_flag,
    scoring_date AS scoring_date
  FROM `global-customer-services-gcs.gcs_north_star.accounts` a
  JOIN active_contract   ac USING (account_id)
  JOIN component_d       d  USING (account_id)
  JOIN component_c       c  USING (account_id)
  JOIN component_t       t  USING (account_id)
  JOIN component_r       r  USING (account_id)
  JOIN component_b       b  USING (account_id)
  JOIN expansion_flag_cte ef USING (account_id)
)

SELECT
  *,
  CASE
    WHEN avr_score >= 75 THEN 'Green'
    WHEN avr_score >= 50 THEN 'Yellow'
    ELSE                       'Red'
  END AS band
FROM avr
ORDER BY avr_score ASC;
