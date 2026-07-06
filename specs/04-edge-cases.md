# Spec 04 — Edge Cases

The six mandated anomalies. Each is injected by `src/generate/anomalies.py`
**after** the clean-data pass, so the injection is deterministic and countable.

## #1 — Spike & Drop

**Target:** 5% of accounts (50 accounts)

**Selection:** `random.sample(all_account_ids, 50)`

**Mechanism:**
1. Compute the account's total annual credit budget from its first contract
2. Delete existing daily_usage_logs for those 50 accounts
3. In month 1 of the contract (30 days from start_date), generate daily logs
   whose sum ≈ 90% of the annual budget. Distribute across 25–30 days with a
   lognormal daily multiplier
4. In months 2–12, generate very light usage: Bernoulli(p=0.1) days with
   ~2% of daily target

**Detectable signature:** month-1 usage ÷ annual usage ≥ 0.85

**Effect on AVR:** high CV → C ≈ 0 → AVR capped near 60 by the C component's 30% weight

---

## #2 — Shelfware

**Target:** 10% of accounts (100 accounts, disjoint from #1)

**Selection:** `random.sample(remaining_account_ids, 100)`

**Mechanism:**
1. Delete all daily_usage_logs for these accounts (zero usage)
2. Force their `annual_commit_dollars` to the upper end of their segment
   (Enterprise: $800K+, Mid-Market: $100K+) so shelfware is "expensive"
3. Support tickets: reduce to ~30% of normal volume (customers not using don't file tickets)

**Detectable signature:** account has ≥ 1 active contract AND zero rows in `daily_usage_logs`

**Effect on AVR:** D=0, C=0, B=0 → AVR = 25T + 15R ≈ 15–40 (Red)

---

## #3 — Consistent Overages

**Target:** 15% of accounts (150 accounts, disjoint from #1 and #2)

**Selection:** `random.sample(remaining_account_ids, 150)`

**Mechanism:**
1. For each of the 12 months in the contract, compute a monthly multiplier
   uniformly in [1.20, 1.60]
2. Regenerate daily logs so each month's rollup equals
   `included_monthly_compute_credits * multiplier`
3. Distribute daily via lognormal noise (moderate)

**Detectable signature:** ≥ 6 months where monthly_consumed ≥ 1.20 × included_monthly_compute_credits

**Effect on AVR:** D=1 (capped), C≈1 (steady), B=1 (capped) → AVR ≈ 90+
**Effect on Expansion flag:** true (trailing 3mo > 120% of allotment)

---

## #4 — Mid-Year Expansions

**Target:** 30 accounts (disjoint from #1, #2, #3)

**Selection:** `random.sample(remaining_account_ids, 30)`

**Mechanism:**
1. For each selected account, find its base contract
2. Insert a **second** contract row with:
   - `contract_id` = next CTR-######
   - `start_date` = base.start_date + random(120, 270) days (months 4–9)
   - `end_date` = base.end_date + random(180, 365) days (extends beyond original)
   - `annual_commit_dollars` = base.annual_commit_dollars × uniform(1.5, 3.0)
   - `included_monthly_compute_credits` derived from new commit
   - `contract_type` = `'Expansion'`
3. Increase daily usage after expansion start_date to reflect ~80% of the
   *new* (higher) included_monthly_compute_credits

**Detectable signature:** ≥ 2 contracts for same account with overlapping [start, end] date ranges

**Effect on AVR:** Denominators switch to the larger contract's credits mid-year;
metric SQL resolves ambiguity by joining to the *most recent active contract*
on the scoring date

---

## #5 — Orphaned / Rogue Usage

**Target:** 200 orphan logs + 100 out-of-window logs

**Mechanism:**

**Orphans (200 rows):**
- Generate 200 rows with `account_id = 'UUID-<random 8hex>'` (guaranteed not
  in `accounts`)
- Random dates within the run window
- Random compute_credits_consumed values

**Out-of-window (100 rows):**
- Randomly select 100 real accounts
- Generate 1 log row each with a date either:
  - 50 rows: 1–90 days **before** the account's earliest contract start
  - 50 rows: 1–90 days **after** the account's latest contract end
- Compute credits normal

**Detectable signature:**
- Orphans: `daily_usage_logs.account_id` not in `accounts.account_id` → count ≥ 150
- Out-of-window: log row exists but no active contract on that date → count ≥ 75

**Effect on AVR:** Both categories filtered by INNER JOIN + contract-window
predicate in `north_star_metric.sql`. They **do not** distort scores. QA
harness verifies the filter works.

---

## #6 — Approaching Cap (Expansion Candidates)

**Target:** 10% of accounts (100 accounts, disjoint from #1–#4)

**Selection:** `random.sample(remaining_account_ids, 100)` — carved from the
Normal population; injection runs at the END of the anomaly sequence to
preserve determinism of cohorts #1–#4.

**Mechanism:**
1. Delete existing daily_usage_logs for these accounts
2. For each 30-day generator-month within the contract, draw a multiplier
   `m = 0.90 + random() * 0.30` (uniform in `[0.90, 1.20)`, strictly below
   the overage bar)
3. Regenerate daily logs so each generator-month's rollup equals
   `included_monthly_compute_credits * m`
4. Distribute daily via uniform noise + baseline (`random + 0.5`)

**Detectable signature:** ≥ 6 calendar months where
`monthly_consumed ∈ [0.80, 1.20) × included_monthly_compute_credits`
(QA band widened from generator band to absorb month-boundary bleeding at
contract start/end).

**Effect on AVR:** D≈1, C≈1 (steady), B≈0.5–0.9 depending on multiplier →
AVR ≈ 75–90 (Green).
**Effect on Expansion flag:** true when trailing 3-month rolling usage
sum ≥ 0.90 × (3 × monthly_allotment) AND days-to-renewal ≤ 180.

---

## Injection accounting

After all 6 passes, expected disjoint account counts:

| Category | Count |
|---|---|
| Spike & Drop | 50 |
| Shelfware | 100 |
| Consistent Overages | 150 |
| Mid-Year Expansions | 30 |
| Approaching Cap | 100 |
| **Sum of "special" accounts** | **430** |
| Normal (clean-generation) accounts | ~570 |
| **Total accounts** | **1,000** |

The five "special" categories are **mutually exclusive** — an account cannot
be both shelfware and approaching-cap, etc. Enforced by `random.sample` on
the shrinking remaining_ids pool in `anomalies.py`.
