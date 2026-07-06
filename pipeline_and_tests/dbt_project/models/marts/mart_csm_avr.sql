-- mart_csm_avr.sql
-- ============================================================================
-- CSM-grain rollup of AVR.
-- ONE row per (snapshot_date, csm_id) with book-of-business KPIs.
--
-- FK note: accounts.rep_id is the CSM foreign key (name-mismatch with
-- csm_reps.csm_id). Join happens in this mart via `USING (csm_id)` after
-- aliasing rep_id → csm_id in the accounts CTE.
--
-- Spec: 07-csm-rollup.md
-- ============================================================================

WITH accounts_snap AS (
    SELECT
        m.snapshot_date,
        acc.rep_id AS csm_id,        -- alias to canonical CSM identifier
        m.account_id,
        m.annual_commit_dollars,
        m.avr_score,
        m.t_score,                   -- for Technical Health rollup
        m.band,
        m.expansion_flag
    FROM {{ ref('mart_account_avr') }} m
    JOIN {{ ref('stg_accounts') }}     acc USING (account_id)
    -- Ramp-period accounts are excluded from CSM rollups entirely (v1 design).
    -- They have NULL avr_score anyway; explicit filter also excludes them from
    -- n_accounts, book_arr, band counts, and expansion counts so the CSM's
    -- book-of-business KPIs reflect only their scoreable accounts. Ramp
    -- accounts remain visible in mart_account_avr (see is_ramp_period flag);
    -- CS-Ops onboarding health is tracked via a separate workflow.
    WHERE NOT IFNULL(m.is_ramp_period, FALSE)
),

per_csm AS (
    SELECT
        snapshot_date,
        csm_id,
        COUNT(DISTINCT account_id)                                 AS n_accounts,
        SUM(annual_commit_dollars)                                 AS book_arr,
        AVG(avr_score)                                             AS avg_avr,
        SAFE_DIVIDE(
            SUM(annual_commit_dollars * avr_score),
            SUM(annual_commit_dollars)
        )                                                          AS arr_weighted_avr,
        -- Technical Health rollup (added 2026-07-04 per exec ask). Surfaces
        -- the T-component of AVR (weight 0.25) as a stand-alone "how
        -- operationally healthy is this CSM's book?" signal on the
        -- leaderboard. Two forms expose the same duality as AVR:
        --   avg_technical_health         = each account 1 vote
        --   arr_weighted_technical_health = bigger books count more
        -- Both scaled [0,1] → [0,100] to match the AVR display convention;
        -- same 75/50 band thresholds as AVR.
        AVG(t_score) * 100                                         AS avg_technical_health,
        SAFE_DIVIDE(
            SUM(annual_commit_dollars * t_score),
            SUM(annual_commit_dollars)
        ) * 100                                                    AS arr_weighted_technical_health,
        COUNTIF(band = 'Green')                                    AS n_green,
        COUNTIF(band = 'Yellow')                                   AS n_yellow,
        COUNTIF(band = 'Red')                                      AS n_red,
        COUNTIF(expansion_flag)                                    AS n_expansion_opps,
        SUM(IF(expansion_flag, annual_commit_dollars, 0))          AS expansion_pipeline_arr
    FROM accounts_snap
    GROUP BY 1, 2
),

-- Emit a row for every (snapshot_date, csm_id) even if the CSM has zero
-- active accounts on that snapshot (spec 07 § "Handling CSMs with zero
-- active accounts"). Downstream time-series queries need continuous rows.
grid AS (
    SELECT
        s.snapshot_date,
        r.csm_id,
        r.csm_name,
        r.region
    FROM {{ ref('int_snapshot_dates') }} s
    CROSS JOIN {{ ref('stg_csm_reps') }} r
)

SELECT
    g.snapshot_date,
    g.csm_id,
    g.csm_name,
    g.region,
    IFNULL(p.n_accounts,             0)      AS n_accounts,
    IFNULL(p.book_arr,               0)      AS book_arr,
    p.avg_avr,
    p.arr_weighted_avr,
    p.avg_technical_health,
    p.arr_weighted_technical_health,
    IFNULL(p.n_green,                0)      AS n_green,
    IFNULL(p.n_yellow,               0)      AS n_yellow,
    IFNULL(p.n_red,                  0)      AS n_red,
    SAFE_DIVIDE(p.n_red, p.n_accounts)       AS pct_red,
    IFNULL(p.n_expansion_opps,       0)      AS n_expansion_opps,
    IFNULL(p.expansion_pipeline_arr, 0)      AS expansion_pipeline_arr
FROM grid g
LEFT JOIN per_csm p
  USING (snapshot_date, csm_id)
