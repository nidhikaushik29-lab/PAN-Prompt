-- mart_account_avr.sql
-- ============================================================================
-- Account-grain AVR time series.
-- ONE row per (snapshot_date, account_id) with the AVR score, all five
-- component scores (D/C/T/R/B), the band, and the Expansion Opportunity flag.
--
-- This is the primary deliverable for the "Account Value Realization" metric.
-- Reads:  int_snapshot_dates
--         int_account_contract_active
--         int_account_snapshot_usage
--         int_account_snapshot_tickets
--         int_account_snapshot_health
--         stg_accounts
--
-- Spec: 01-north-star-metric.md  (formula + edge case handling)
-- ============================================================================

WITH active AS (
    SELECT * FROM {{ ref('int_account_contract_active') }}
),

usage AS (
    SELECT * FROM {{ ref('int_account_snapshot_usage') }}
),

tickets AS (
    SELECT * FROM {{ ref('int_account_snapshot_tickets') }}
),

health AS (
    SELECT * FROM {{ ref('int_account_snapshot_health') }}
),

-- ============ D: Deployment Depth ============
component_d AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        LEAST(1.0, IFNULL(SAFE_DIVIDE(
            u.credits_last_month,
            a.included_monthly_compute_credits
        ), 0)) AS d_score
    FROM active a
    LEFT JOIN usage u USING (snapshot_date, account_id)
),

-- ============ C: Consumption Sustainability ============
component_c AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        CASE
            WHEN u.mean_90d IS NULL OR u.mean_90d = 0 OR u.n_days_90d < 10 THEN 0.0
            ELSE GREATEST(0.0, LEAST(1.0, 1.0 - SAFE_DIVIDE(u.sd_90d, u.mean_90d)))
        END AS c_score
    FROM active a
    LEFT JOIN usage u USING (snapshot_date, account_id)
),

-- ============ T: Technical Health ============
-- Blend of three signals (weights sum to 1.0):
--   0.55 × T_color     — latest CSM-entered health color (Green/Yellow/Red;
--                        missing → 0.5 "unknown", NEVER 1.0)
--   0.30 × T_tickets   — age-weighted open-ticket load; includes sev-3 at
--                        0.05 weight; each ticket counts up to 2× when
--                        ≥30 days old (linear ramp)
--   0.15 × T_trend     — 30-day trend in ticket load: bonus for improvement,
--                        penalty for regression, 0.5 (neutral) if flat or
--                        first-ever snapshot for the account
--
-- Calibration:
--   1 fresh sev-1 open        → T_tickets ≈ 0.875
--   3 fresh sev-1 open        → T_tickets ≈ 0.625
--   8 fresh sev-1 open        → T_tickets = 0
--   30-day-old sev-1          → counts as 2× a fresh sev-1
--   20 fresh sev-3 open       → T_tickets ≈ 0.75  (sev-3 is intentionally
--                                                  noise-level so a routine
--                                                  low-priority backlog does
--                                                  not dominate the score)
--   +4 pts load vs last month → T_trend = 0    (max penalty)
--   −4 pts load vs last month → T_trend = 1    (max bonus)
--   flat / first snapshot     → T_trend = 0.5  (neutral)
--
-- Design invariants preserved:
--   1. Missing health color still defaults to 0.5 (unknown), not 1.0 — a
--      silently-broken feed cannot inflate scores.
--   2. Shelfware ceiling AVR unchanged at 40 (T max = 1.0 in the theoretical
--      best case; typical shelfware still lands in Red).
--   3. T ∈ [0, 1] preserved — every sub-term is clamped independently.
--
-- Prior formula (before 2026-07-04): T = 0.6·T_color + 0.4·T_tickets_v1 where
-- T_tickets_v1 = 1 - LEAST(1, (open_sev1×0.5 + open_sev2×0.2)/3). Enhanced
-- per exec ask to (a) surface sev-3 as noise-level signal, (b) penalize
-- unresolved-and-aging tickets, (c) reward month-over-month improvement.
-- See specs/01-north-star-metric.md § T for the design rationale.
component_t AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        IFNULL(t.open_sev1, 0)                                          AS open_sev1,
        IFNULL(t.open_sev2, 0)                                          AS open_sev2,
        IFNULL(t.open_sev3, 0)                                          AS open_sev3,
        IFNULL(t.age_weighted_load, 0.0)                                AS age_weighted_load,
        IFNULL(t.prev_age_weighted_load,
               IFNULL(t.age_weighted_load, 0.0))                        AS prev_age_weighted_load,
        h.latest_color,
        (
              0.55 * CASE h.latest_color
                         WHEN 'Green'  THEN 1.0
                         WHEN 'Yellow' THEN 0.5
                         WHEN 'Red'    THEN 0.0
                         ELSE               0.5   -- missing = unknown
                     END
            + 0.30 * (1.0 - LEAST(1.0, IFNULL(t.age_weighted_load, 0.0) / 4.0))
            + 0.15 * (
                0.5 - LEAST(0.5, GREATEST(-0.5,
                    (
                        IFNULL(t.age_weighted_load, 0.0)
                      - IFNULL(t.prev_age_weighted_load, IFNULL(t.age_weighted_load, 0.0))
                    ) / 4.0
                ))
              )
        ) AS t_score
    FROM active a
    LEFT JOIN tickets t USING (snapshot_date, account_id)
    LEFT JOIN health  h USING (snapshot_date, account_id)
),

-- ============ R: Retention Signal ============
component_r AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        a.days_to_renewal,
        CASE
            WHEN a.days_to_renewal > 180 THEN 1.0
            WHEN a.days_to_renewal BETWEEN 60 AND 180 THEN 0.75
            WHEN a.days_to_renewal BETWEEN 0 AND 59
                 AND NOT IFNULL(h.had_red_last_30d, FALSE) THEN 1.0
            WHEN a.days_to_renewal BETWEEN 0 AND 59
                 AND IFNULL(h.had_red_last_30d, FALSE) THEN 0.25
            ELSE 0.0
        END AS r_score
    FROM active a
    LEFT JOIN health h USING (snapshot_date, account_id)
),

-- ============ B: Bookings Realization ============
component_b AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        LEAST(1.0, IFNULL(SAFE_DIVIDE(
            u.credits_ytd_contract,
            a.included_monthly_compute_credits * (a.days_in_contract / 30.0)
        ), 0)) AS b_score
    FROM active a
    LEFT JOIN usage u USING (snapshot_date, account_id)
),

-- ============ Expansion Opportunity flag ============
expansion AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        (
              IFNULL(u.credits_last_3mo, 0)
              >= {{ var("expansion_overage_threshold") }}
                * (3 * a.included_monthly_compute_credits)
          AND a.days_to_renewal <= {{ var("expansion_days_to_renewal") }}
        ) AS expansion_flag
    FROM active a
    LEFT JOIN usage u USING (snapshot_date, account_id)
),

assembled AS (
    SELECT
        a.snapshot_date,
        a.account_id,
        acc.company_name,
        acc.industry,
        acc.account_segment,
        acc.rep_id,
        csm.region,
        csm.csm_name,
        a.contract_id,
        a.contract_type,
        a.annual_commit_dollars,
        a.included_monthly_compute_credits,
        a.days_to_renewal,
        a.days_in_contract,
        -- Ramp-period flag: accounts younger than ramp_period_days are still
        -- onboarding and are NOT scored by AVR v1 (see spec 01 § Known
        -- limitations). Component scores are still populated for audit /
        -- debug purposes, but avr_score is NULLed and band = 'Onboarding' so
        -- downstream aggregations naturally exclude them.
        (a.days_in_contract < {{ var("ramp_period_days") }}) AS is_ramp_period,
        d.d_score,
        c.c_score,
        t.t_score,
        r.r_score,
        b.b_score,
        t.open_sev1,
        t.open_sev2,
        t.open_sev3,
        t.latest_color,
        CASE
            WHEN a.days_in_contract < {{ var("ramp_period_days") }} THEN NULL
            ELSE ROUND(100 * (
                  0.20 * d.d_score
                + 0.30 * c.c_score
                + 0.25 * t.t_score
                + 0.15 * r.r_score
                + 0.10 * b.b_score
            ), 1)
        END AS avr_score,
        e.expansion_flag
    FROM active a
    JOIN {{ ref('stg_accounts') }} acc USING (account_id)
    LEFT JOIN {{ ref('stg_csm_reps') }} csm ON acc.rep_id = csm.csm_id
    JOIN component_d d USING (snapshot_date, account_id)
    JOIN component_c c USING (snapshot_date, account_id)
    JOIN component_t t USING (snapshot_date, account_id)
    JOIN component_r r USING (snapshot_date, account_id)
    JOIN component_b b USING (snapshot_date, account_id)
    JOIN expansion   e USING (snapshot_date, account_id)
)

SELECT
    *,
    CASE
        WHEN is_ramp_period                                     THEN 'Onboarding'
        WHEN avr_score >= {{ var("band_green_cutoff")  }}       THEN 'Green'
        WHEN avr_score >= {{ var("band_yellow_cutoff") }}       THEN 'Yellow'
        ELSE                                                         'Red'
    END AS band
FROM assembled
