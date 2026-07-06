# Spec 01 — North Star Metric: Account Value Realization (AVR)

## Definition

**Account Value Realization (AVR)** is a composite score, 0–100, computed
**per account, per day**. It intentionally penalizes shelfware, spike-and-drop
patterns, and technical instability, while allowing consistent overages to
score well *and* raise a separate Expansion Opportunity flag.

## Formula

```
AVR = 100 × (0.20·D + 0.30·C + 0.25·T + 0.15·R + 0.10·B)
```

Each component is normalized to `[0, 1]` before weighting.

### D — Deployment Depth (weight 0.20)

Fraction of the account's `included_monthly_compute_credits` consumed in the
**most recent complete calendar month**, capped at 1.0.

```
D = MIN(1.0, monthly_consumed / included_monthly_compute_credits)
```

- Shelfware accounts → D ≈ 0
- Fully deploying accounts → D ≈ 1
- Overage accounts → D = 1.0 (capped — overage is credited via the Expansion flag, not double-counted here)

### C — Consumption Sustainability (weight 0.30)

Rewards stable usage; penalizes spike-and-drop.

```
CV = STDDEV(daily_usage_last_90d) / NULLIF(AVG(daily_usage_last_90d), 0)
C  = GREATEST(0, LEAST(1, 1 - CV))
```

- Steady usage → low CV → C ≈ 1
- Spike-and-drop → high CV → C ≈ 0
- All-zeros (shelfware) → NULL AVG → C treated as 0

### T — Technical Health (weight 0.25)

Blend of three signals (sub-weights sum to 1.0):

```
T_color   = CASE health_color WHEN 'Green'  THEN 1.0
                              WHEN 'Yellow' THEN 0.5
                              WHEN 'Red'    THEN 0.0
                              ELSE               0.5 END   -- missing = unknown

age_weighted_load = SUM_open_tickets(sev_weight × age_multiplier)
  where sev_weight     = {1: 0.50, 2: 0.20, 3: 0.05}
        age_multiplier = 1 + LEAST(1, age_days / 30)       -- 1× fresh, 2× ≥30d

T_tickets = 1 - LEAST(1, age_weighted_load / 4.0)

T_trend   = 0.5 - LEAST(0.5, GREATEST(-0.5,
              (age_weighted_load - prev_snapshot_load) / 4.0
            ))
              -- bonus for improvement, penalty for regression
              -- first-ever snapshot → prev falls back to current → T_trend = 0.5

T = 0.55 × T_color + 0.30 × T_tickets + 0.15 × T_trend
```

Calibration:

- 1 fresh sev-1 open        → `T_tickets` ≈ 0.875
- 3 fresh sev-1 open        → `T_tickets` ≈ 0.625
- 8 fresh sev-1 open        → `T_tickets` = 0
- 30-day-old sev-1          → counts as 2× a fresh sev-1
- 20 fresh sev-3 open       → `T_tickets` ≈ 0.75 (sev-3 intentionally noise-level)
- +4 pts load vs last month → `T_trend` = 0    (max penalty)
- −4 pts load vs last month → `T_trend` = 1    (max bonus)
- flat / first snapshot     → `T_trend` = 0.5  (neutral)

Missing-data invariant: if no `health_color` row exists for the day, `T_color`
defaults to 0.5 (unknown), NOT 1.0. A silently-broken feed cannot inflate T.

Design intent (added 2026-07-04 per exec ask, replacing the prior
`T = 0.6·T_color + 0.4·T_tickets_v1` formula):

1. **Sev-3 no longer ignored.** Sev-3 is ~85% of ticket volume; entirely
   omitting it made T blind to routine operational load. Weighted at 0.05
   (10× smaller than sev-1) so a big low-priority backlog still shows up
   without dominating.
2. **Age decay rewards fast MTTR.** A stale sev-1 counts up to 2× a fresh
   one — teams that close tickets quickly score better than teams that let
   them accumulate.
3. **30-day trend surfaces momentum.** An account whose ticket load is
   dropping month-over-month gets a small bonus; one whose load is rising
   gets a small penalty. Prevents T from being a purely static "snapshot
   of the moment" signal.

The T-component is rolled up to CSM level in `mart_csm_avr` as
`avg_technical_health` (each account 1 vote) and `arr_weighted_technical_health`
(bigger books count more), both scaled 0–100. Surfaced on the CSM leaderboard
as the **Technical Health** column — see specs/08-dashboard.md §4.

### R — Retention Signal (weight 0.15)

Rewards accounts approaching renewal with no red health flags.

```
days_to_renewal = DATE_DIFF(contract_end_date, current_date, DAY)

R = CASE
      WHEN days_to_renewal > 180 THEN 1.0                              -- far from renewal
      WHEN days_to_renewal BETWEEN 60 AND 180 THEN 0.75
      WHEN days_to_renewal BETWEEN 0 AND 59 AND no_red_in_last_30d THEN 1.0
      WHEN days_to_renewal BETWEEN 0 AND 59 AND red_in_last_30d    THEN 0.25
      WHEN days_to_renewal < 0 THEN 0.0                                 -- expired/lapsed
    END
```

### B — Bookings Realization (weight 0.10)

Year-to-date consumption vs. prorated annual commit, capped at 1.0.

```
prorated_included = included_monthly_compute_credits * months_elapsed_in_contract
B = MIN(1.0, consumed_since_contract_start / prorated_included)
```

## Bands

| AVR Range | Band | Meaning |
|---|---|---|
| ≥ 75 | Green | Healthy, value realized |
| 50 – 74 | Yellow | At risk, intervene |
| < 50 | Red | Immediate action required |

## Expansion Opportunity Flag

A **separate** boolean, not part of AVR:

```
expansion_flag = trailing_3_month_usage >= 0.90 * (3 * included_monthly_compute_credits)
                 AND days_to_renewal <= 180
```

Rationale: consistent overages are *good news* — they signal the customer needs
a bigger contract. Rolling them into AVR would inflate the score and hide the
commercial opportunity. Keeping them separate lets the CSM/SC team convert them.

## Reference SQL

Full implementation lives at `src/bq/north_star_metric.sql`. High-level structure:

```sql
WITH usage_daily AS (
  SELECT account_id, date, SUM(compute_credits_consumed) AS credits
  FROM daily_usage_logs
  GROUP BY 1, 2
),
active_contract AS (
  SELECT c.*, DATE_DIFF(c.end_date, CURRENT_DATE(), DAY) AS days_to_renewal
  FROM contracts c
  WHERE CURRENT_DATE() BETWEEN c.start_date AND c.end_date
),
components AS (
  SELECT
    a.account_id,
    d.date,
    -- D, C, T, R, B computed with window functions over usage_daily,
    -- account_health, and support_tickets
    ...
  FROM accounts a
  JOIN active_contract ac USING (account_id)
  JOIN usage_daily d USING (account_id)
),
scored AS (
  SELECT
    account_id, date,
    100 * (0.20*D + 0.30*C + 0.25*T + 0.15*R + 0.10*B) AS avr,
    ...
  FROM components
)
SELECT
  s.*,
  CASE WHEN avr >= 75 THEN 'Green'
       WHEN avr >= 50 THEN 'Yellow'
       ELSE 'Red' END AS band,
  expansion_flag
FROM scored;
```

## Edge-case handling (mandatory)

The metric is deliberately designed so each of the five Phase 1 anomalies
(specs/04-edge-cases.md) produces the *correct* commercial signal without
special-casing. The table below traces each edge case to the specific SQL /
dbt logic that handles it and the observed AVR range on 2026-01-31.

| # | Edge case | Injected count | Handled by (component / clause) | Observed AVR range | Correct signal |
|---|---|---|---|---|---|
| 1 | Spike & Drop | 50 accounts | **C** — `1 - STDDEV/AVG` over trailing 90d. Front-loaded month + 11 near-zero months → very high coefficient of variation → C ≈ 0 → AVR loses full 30 weight | 25–55 | Yellow / Red |
| 2 | Shelfware | 100 accounts | **D** = 0 (no last-month credits), **C** = 0 (fallback when `mean_90d = 0`), **B** = 0 (no YTD credits). Only T and R contribute → ceiling AVR = 25·T + 15·R ≈ 40 | 0–40 (72/72 Red in smoke test) | Red |
| 3 | Consistent Overages | 150 accounts | Overages are **not** penalized: D capped at 1.0, B capped at 1.0, steady overage keeps CV low so C ≈ 1. AVR stays Green. Separate **Expansion Opportunity flag** fires when trailing-3mo ≥ 90% of allotment AND `days_to_renewal ≤ 180` (threshold lowered from 120% to 90% on 2026-07-04 per exec ask — surfaces "approaching cap" candidates as well as true overages) | 80–95 | Green **plus** `expansion_flag = true` |
| 4 | Mid-Year Expansions | 30 accounts | Two contract rows overlap in time. `active_contract` CTE uses `ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY start_date DESC)` and picks the **latest-started** contract — so the larger post-expansion allotment becomes the denominator for D and B | 70–90 (depends on ramp) | Green, no false-Red from denominator swap |
| 5a | Orphaned usage (200 rows) | Random UUIDs, no matching `accounts` row | `clean_usage` CTE = `INNER JOIN accounts`. Orphan logs are dropped before any component is computed | N/A (excluded) | Filtered silently; test `test_orphaned_usage.sql` surfaces them |
| 5b | Out-of-window usage (100 rows) | Real accounts, dates 1–90d before/after contract | `usage_in_window` CTE = `INNER JOIN active_contract ON date BETWEEN start_date AND end_date`. Out-of-window logs are dropped before any component is computed | N/A (excluded) | Filtered silently; test `test_out_of_window_usage.sql` surfaces them |

### Why filtered anomalies are still tested

Rows 5a and 5b are removed by the metric SQL, so they cannot distort a score.
But they are still **data-quality bugs** in the source system that need to be
surfaced upstream. Phase 2 dbt tests (`dbt_project/tests/*.sql`) fail loudly
when these appear, so a data engineer can trace them back to the ingestion
pipeline.

### Design invariants worth preserving

1. **Overages are rewarded commercially, not penalized in AVR.** Rolling them
   into D or B would inflate the health score AND hide the expansion signal.
2. **Shelfware cannot score above ~40.** The three usage-driven components
   (D + C + B = 60% of weight) all collapse to 0.
3. **A single anomaly cannot dominate.** No component exceeds 30% weight, and
   two of them (D and B) are capped at 1.0.
4. **Missing data ≠ good data.** `T_color` defaults to 0.5 (unknown), not 1.0.
   A silently-broken feed can't inflate scores.
5. **New-logo ramp is excluded, not misjudged.** Accounts with
   `days_in_contract < 90` have `avr_score = NULL` and `band = 'Onboarding'`
   (added v1.1, 2026-07-05). D and B compare consumption to a flat allotment,
   and a customer hitting standard enterprise-SaaS onboarding benchmarks
   (20–30% of allotment in month 1) would score as if they were shelfware —
   creating a false-negative "Red" signal that would either burn CSM time
   chasing phantom health or make execs distrust the metric on rollout.
   See §Known limitations (v1) below.

## Known limitations (v1)

**Documented gaps in the v1 formula that are deliberate rather than bugs.**
Each is a design choice that trades scope for shippability; each has a
clearly-documented workaround or successor Phase where a full fix would live.

### 1. New-logo ramp exclusion (v1.1, 2026-07-05)

**Problem.** D (Deployment Depth) uses `credits_last_month / included_monthly_credits`; B (Bookings Realization) uses `credits_ytd_contract / (allotment × months_in_contract)`. Both denominate against a **flat allotment from day 1**. A new customer following a standard enterprise-SaaS onboarding curve — 20–30% of allotment in month 1, ramping to steady-state by month 3 — would score `D ≈ 0.25`, `B ≈ 0.25`, contributing only 5+2.5 = 7.5 out of the 30 points those two components carry. Combined with the C safety valve (`n_days_90d < 10 → C = 0`) firing for the first ~3 months, the account would score deep Red for the entire onboarding period despite being healthy on any operational metric a CSM would recognize.

**Ramp-heavy impact in the current dataset** (verified from raw CSVs):

| Snapshot | Ramping (`days_in_contract < 90`) | % of active book |
|---|---|---|
| 2025-02-28 | 870 / 870 | 100% |
| 2026-01-31 | 141 / 301 | 46.8% |
| 2026-06-30 (default) | 13 / 207 | 6.3% |

**Decision.** Suppress the score during ramp rather than trying to correct it.

Concretely, `mart_account_avr` sets:
- `is_ramp_period = (days_in_contract < 90)` (boolean, `ramp_period_days` var in `dbt_project.yml`)
- `avr_score = NULL` when `is_ramp_period`
- `band = 'Onboarding'` when `is_ramp_period` (evaluated **before** the Green/Yellow/Red cutoffs)
- Component scores `d/c/t/r/b_score` **remain populated** for audit/debug so a data-eng can reason about "why did this customer's D look bad on day 30?" without re-materialising the mart

`mart_csm_avr` filters ramping accounts out of every aggregation unconditionally (`WHERE NOT IFNULL(m.is_ramp_period, FALSE)` in the `accounts_snap` CTE) — CSM attribution is only meaningful for scored accounts.

**Why 90 days.** Industry rule of thumb for "time to first value" in enterprise SaaS. The number is a `dbt_project.yml` `var` (`ramp_period_days`) so it can be tuned per product line without a formula rewrite. Alternatives considered and rejected:

- **Multiplicative D = milestone_rate × usage** — worsens the underlying ramp problem (a customer missing week-1 milestones drops D to 0), requires a milestone-tracking data feed we don't have, and violates the "each component measures ONE thing" design principle
- **90-day grace with weight renormalization** (D and B weights redistributed to C/T/R) — creates a novel scoring mode that would need its own band cutoffs and its own dashboard branch. Adds surface area without adding decision-relevant signal
- **Docs-only warning ("scores <90 days are noisy, use with caution")** — the data violates any bare tenure assumption too aggressively for a caption to save. 388 / 870 accounts were < 30 days into contract on 2025-02-28

**Dashboard behavior.** The sidebar `Tenure` filter (added 2026-07-05) exposes two independent checkboxes — `Include ramped customers` (default ON) and `Include ramping customers` (default OFF) — that control which populations enter aggregate stats and the trend charts. The single-customer Account detail replaces the score UI with an onboarding-explainer block when the selected account is ramping. See `specs/08-dashboard.md § Tenure filter` for the full UX + predicate mapping.

**Successor.** A Phase 6 revisit could introduce an expected-ramp curve (published per Segment × Product-line based on 90-day retrospective on the ramped book), turning D and B into `(consumption ÷ expected(day_n))` ratios. That's a separate design exercise gated on 2+ quarters of Phase 4 shadow data — deliberately not part of v1.

### 2. (reserved)

Future v1 limitations will be documented here as they surface during Phase 4 shadow — this section is expected to grow, not shrink, as real usage exposes edge cases the smoke-test dataset doesn't reach.

## Tuning knobs (all in one place)

Config lives in `src/generate/config.py` and the SQL comments; weights and
thresholds are the levers Phase 2 will A/B test:

- Component weights (must sum to 1.0)
- Green/Yellow/Red band cutoffs
- CV normalization window (90d default)
- Overage threshold for Expansion flag (90% default; was 120% pre-2026-07-04)
- T sub-weights (0.55/0.30/0.15 for color/tickets/trend; enhanced 2026-07-04)
- T ticket-severity weights (sev-1: 0.50, sev-2: 0.20, sev-3: 0.05)
- T ticket-load denominator (4.0) and trend denominator (4.0)
- Ramp-period cutoff (`ramp_period_days = 90` default; added v1.1 2026-07-05 — see § Known limitations)
