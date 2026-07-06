# Spec 05 — Data Quality Tests

`src/validate/quality_checks.py` reads the generated CSVs and asserts every
statement below, then writes `data/qa_report.md` (a Markdown table of PASS/FAIL
per check). Any FAIL blocks the BigQuery load step.

## Row-count assertions (tolerance ±10% unless noted)

| Table | Expected | Tolerance |
|---|---|---|
| csm_reps | 50 | exact |
| accounts | 1,000 | exact |
| contracts | 1,200 | ±10% (1,080 – 1,320) |
| support_tickets | 30,000 | ±25% (22,500 – 37,500) |
| account_health | 50,000 | ±20% (40,000 – 60,000) |
| daily_usage_logs | 200,000 | ±20% (160,000 – 240,000) |

## Referential integrity

| # | Assertion | Expected |
|---|---|---|
| RI-1 | Every `accounts.rep_id` exists in `csm_reps.csm_id` (name-mismatch FK) | 100% |
| RI-2 | Every `contracts.account_id` exists in `accounts.account_id` | 100% |
| RI-3 | Every `support_tickets.account_id` exists in `accounts.account_id` | 100% |
| RI-4 | Every `account_health.account_id` exists in `accounts.account_id` | 100% |
| RI-5 | `daily_usage_logs.account_id` in accounts | ≥ 99.85% (200 orphans expected) |

## Segment/CSM alignment

| # | Assertion |
|---|---|
| SEG-1 | Every account's segment matches its assigned CSM's segment |
| SEG-2 | Enterprise:Mid-Market ratio 40:60 (±3%) in accounts |
| SEG-3 | Enterprise:Mid-Market ratio 40:60 (±5%) in csm_reps |

## Edge-case detection (from spec 04)

| # | Edge case | Assertion | Threshold |
|---|---|---|---|
| EC-1 | Spike & Drop | Accounts with month-1 usage ÷ 12-mo usage ≥ 0.85 | ≥ 45 (target 50) |
| EC-2 | Shelfware | Accounts with active contract but zero usage logs | ≥ 90 (target 100) |
| EC-3 | Overages | Accounts with ≥ 6 months over 120% of allotment | ≥ 140 (target 150) |
| EC-4 | Expansions | Accounts with ≥ 2 contracts having overlapping active date ranges | ≥ 25 (target 30) |
| EC-5a | Orphan logs | Rows in daily_usage_logs whose account_id is not in accounts | ≥ 150 (target 200) |
| EC-5b | Out-of-window | Rows in daily_usage_logs with no covering contract on the log date | ≥ 75 (target 100) |
| EC-6 | Approaching Cap | Accounts with ≥ 6 calendar months where consumption ∈ [0.80, 1.20) × allotment | ≥ 70 (target 100) |

## Distribution sanity

| # | Assertion |
|---|---|
| DIST-1 | Severity mix in support_tickets within ±5 percentage points of [sev1=3, sev2=12, sev3=85] |
| DIST-2 | annual_commit_dollars for Enterprise segment: min ≥ $200K, max ≤ $2M |
| DIST-3 | annual_commit_dollars for Mid-Market segment: min ≥ $25K, max ≤ $200K |
| DIST-4 | account_health.health_color values are only in {Green, Yellow, Red} |
| DIST-5 | Every date in every table falls in [2025-01-01, 2026-06-30] EXCEPT out-of-window rogue logs (which are expected outside) |

## Metric-readiness assertions

| # | Assertion |
|---|---|
| MET-1 | After a mock AVR run, at least 3 distinct bands (Green/Yellow/Red) are represented across accounts |
| MET-2 | Shelfware accounts (EC-2) score in Red band |
| MET-3 | At least 50 accounts flagged Expansion Opportunity (must have an active contract on the scoring date, so ~50% of overage cohort) |

MET-1/2/3 require the actual metric SQL against BigQuery, so they run as a
**secondary** validation step after `make load` — captured in a separate
`data/metric_smoke.md` file, not blocking the load.

## Output format

`data/qa_report.md` layout:

```markdown
# QA Report — GCS North Star Dataset
Generated: 2026-07-03 18:52 UTC · Seed: 42

## Summary
Total checks: 28 · Passed: 28 · Failed: 0 · Overall: ✅ PASS

## Row Counts
| Table | Expected | Actual | Status |
| ...

## Referential Integrity
| ...

## Edge Case Detection
| ...
```

Exit code 0 on all-pass, 1 on any fail.
