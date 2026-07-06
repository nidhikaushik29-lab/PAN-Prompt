# Spec 03 — Generation Rules

## Determinism

- **Random seed:** `42` (constant in `src/generate/config.py`)
- **Faker seed:** `42`
- **NumPy seed:** `42`
- Every generator uses these seeds; two runs on the same commit produce byte-identical CSVs

## Time window

- **Start:** `2025-01-01`
- **End:** `2026-06-30` (18 months)
- Rationale: 18 months covers full 12-month contract cycles, mid-year expansions,
  and a renewal wave in Q1 2026 — richer than a strict 12-month window

## Volumes (exact targets)

| Table | Rows |
|---|---|
| `csm_reps` | 50 |
| `accounts` | 1,000 |
| `contracts` | ~1,200 (1,000 base + 200 renewals/expansions) |
| `support_tickets` | ~30,000 |
| `account_health` | ~50,000 (weekly per account, trimmed to active weeks) |
| `daily_usage_logs` | ~200,000 (before orphan additions) |

`~` = within ±5% due to distribution randomness; QA harness enforces tolerance.

## Distributions

### CSM reps
- Segment split: 40% Enterprise, 60% Mid-Market (20 Enterprise CSMs, 30 Mid-Market)
- Region: 45% AMER, 30% EMEA, 15% APAC, 10% JAPAC
- Hire dates uniform between 2020-01-01 and 2024-12-31

### Accounts
- Segment split: 40% Enterprise, 60% Mid-Market
- Industry: weighted — Financial Services 20%, Technology 20%, Healthcare 15%, Retail 15%, Manufacturing 15%, Media 10%, Public Sector 5%
- CSM assignment: each account gets a CSM of matching segment
- Signup dates: uniform between 2022-01-01 and 2025-06-01

### Contracts (base pass — before anomaly injection)
- Every account gets ≥ 1 contract with `start_date` = MAX(account.signup_date, 2025-01-01) rounded to nearest month
- `end_date` = start_date + 365 days
- ~200 accounts get a 2nd contract (renewal) starting ~365 days after the first
- **Annual commit dollars** (log-uniform within segment):
  - Enterprise: 10^log-uniform($200K, $2M)
  - Mid-Market: 10^log-uniform($25K, $200K)
- **Included monthly compute credits** = `ROUND(annual_commit_dollars / 12 / $0.05)`
  - Priced at $0.05/credit → $500K commit = 833K credits/month

### Support tickets
- Per active month per account, generate `Poisson(λ)` tickets where λ depends on segment:
  - Enterprise: λ = 3.5 tickets/month
  - Mid-Market: λ = 1.2 tickets/month
- Severity: multinomial [1=0.03, 2=0.12, 3=0.85]. Stored as INT64. Severity 3 collapses the previous P3+P4 (low priority) into one bucket
- Product area: multinomial [Compute 0.30, Storage 0.15, Networking 0.10, Auth 0.10, API 0.20, UI 0.10, Billing 0.05]
- Resolution time:
  - Severity 1: Exponential mean = 1 day
  - Severity 2: Exponential mean = 3 days
  - Severity 3: Exponential mean = 15 days (weighted avg of former P3=10d + P4=21d)
- Status:
  - 5% Open (no closed_date, opened_date within last 30 days of run window)
  - 10% In Progress
  - 15% Resolved
  - 70% Closed

### Daily usage logs (base pass — before anomaly injection)
- For each active contract, generate one row per day with probability 0.55 (~55% active days)
- **Daily credits consumed** per active day:
  - Mean daily target = `included_monthly_compute_credits / 30 * multiplier`
  - Multiplier ~ LogNormal(μ=0, σ=0.35) — most days near target, occasional 2× days
  - Result rounded to nearest 100
- Yields ~200K rows before orphan additions

### Account health (weekly rollup)
- One row per account per calendar week where the account has an active contract
- `compute_credits_consumed` = sum of daily logs Mon-Sun
- `health_color` derived per rules in spec 02

## Ordering of generation passes

1. `csm_reps.py` — no dependencies
2. `accounts.py` — depends on csm_reps
3. `contracts.py` — depends on accounts; base contracts only
4. `usage.py` — depends on contracts; daily logs, clean
5. `support_tickets.py` — depends on contracts (need active windows)
6. `anomalies.py` — reads all above tables, injects 5 edge cases (spec 04)
7. `health.py` — LAST; rolls up final usage into weekly health snapshots

Anomalies must be injected **before** health rollup so `account_health` reflects
the anomalous states (e.g., a shelfware account shows red).

## ID formatting

| Entity | Format | Example |
|---|---|---|
| csm | `CSM-####` | `CSM-0007` |
| account | `ACCT-######` | `ACCT-000042` |
| contract | `CTR-######` | `CTR-000123` |
| ticket | `TCK-######` | `TCK-005678` |
| log | `LOG-#######` | `LOG-0123456` |
| orphan log account_id | `UUID-<8hex>` | `UUID-a3f9c2e1` |

## Output format

- All tables written to `data/raw/<table>.csv` with header row
- Dates in ISO 8601 (`YYYY-MM-DD`)
- No thousands separators on numeric columns
- UTF-8 encoding
