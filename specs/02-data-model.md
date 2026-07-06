# Spec 02 — Data Model

## Entity-relationship overview

```
                           ┌──────────────────┐
                           │    csm_reps      │
                           │  (~50 rows)      │
                           │  PK: csm_id      │
                           └────────┬─────────┘
                                    │ 1
                                    │
                                    │ N
                           ┌────────▼─────────┐          ┌──────────────────────┐
                           │    accounts      │ 1      N │      contracts       │
                           │  (~1,000 rows)   ├──────────►  (~1,200 rows)       │
                           │  PK: account_id  │          │  PK: contract_id     │
                           │  FK: rep_id      │          │  FK: account_id      │
                           └────┬───────────┬─┘          │  contract_type       │
                                │ 1       1 │            │  overlapping OK      │
                              N │           │ N          └──────────────────────┘
                    ┌───────────▼──┐   ┌────▼──────────────────┐
                    │support_tickets│   │  daily_usage_logs     │
                    │(~30,000 rows) │   │  (~200,000 rows)      │
                    │PK: ticket_id  │   │  PK: log_id           │
                    │FK: account_id │   │  FK: account_id*      │
                    │severity 1-3   │   │  * intentionally      │
                    └───────────────┘   │    violated for       │
                                        │    edge case #5       │
                                        └────┬──────────────────┘
                                             │ aggregated to daily
                                             ▼
                                    ┌──────────────────────┐
                                    │   account_health     │
                                    │   (~50,000 rows)     │
                                    │   daily snapshot     │
                                    │   FK: account_id     │
                                    │   + health_color     │
                                    └──────────────────────┘
```

## Table specifications

### `csm_reps` (~50 rows)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `csm_id` | STRING | NO | PK; format `CSM-0001`..`CSM-0050` |
| `name` | STRING | NO | Faker.name() |
| `region` | STRING | NO | one of `AMER`, `EMEA`, `APAC`, `JAPAC` |
| `segment` | STRING | NO | `Enterprise` or `Mid-Market` |
| `hire_date` | DATE | NO | between 2020-01-01 and 2024-12-31 |

### `accounts` (~1,000 rows)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `account_id` | STRING | NO | PK; format `ACCT-000001`..`ACCT-001000` |
| `company_name` | STRING | NO | Faker.company() |
| `industry` | STRING | NO | one of Financial Services, Healthcare, Retail, Manufacturing, Technology, Media, Public Sector |
| `rep_id` | STRING | NO | FK → `csm_reps.csm_id` (matches segment). Column name intentionally differs from PK to preserve business-side naming (see "Column naming decision" below) |
| `segment` | STRING | NO | `Enterprise` or `Mid-Market` (must match assigned CSM's segment) |
| `signup_date` | DATE | NO | between 2022-01-01 and 2025-06-01; ≤ first contract start_date |

Segment ratio: **40% Enterprise / 60% Mid-Market**.

### `contracts` (~1,200 rows)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `contract_id` | STRING | NO | PK; format `CTR-000001`..`CTR-001200` |
| `account_id` | STRING | NO | FK → `accounts.account_id` |
| `start_date` | DATE | NO | ≥ account signup_date |
| `end_date` | DATE | NO | typically start_date + 365 days |
| `annual_commit_dollars` | NUMERIC | NO | Enterprise: $200K–$2M; Mid-Market: $25K–$200K |
| `included_monthly_compute_credits` | INT64 | NO | derived: annual_commit_dollars / 12 / $0.05 (i.e., $0.05 per credit) |
| `contract_type` | STRING | NO | `New`, `Renewal`, or `Expansion` |

Notes:
- ~200 accounts will have 2+ contracts (renewals or expansions)
- 30 accounts will have **overlapping** active contracts from mid-year Expansions (edge case #4)
- Expansions carry `contract_type='Expansion'` and typically 1.5×–3× the prior commit

**Contract-overlap rules** (asserted by `tests/test_overlapping_contracts_unexpected.sql`):
- Renewals may start up to **15 days before** the prior contract's `end_date` — this
  models real-world early renewals where customers sign next year's contract before
  the current one expires. Yields ~60 New↔Renewal overlaps organically.
- Expansions overlap by construction with the underlying New or Renewal (EC-4).
- **Same-type** overlaps (New/New, Renewal/Renewal, Expansion/Expansion) are
  disallowed and would indicate a generator bug.

### `support_tickets` (~30,000 rows)

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `ticket_id` | STRING | NO | PK; format `TCK-000001`..`TCK-030000` |
| `account_id` | STRING | NO | FK → `accounts.account_id` |
| `opened_date` | DATE | NO | within account's active contract window |
| `closed_date` | DATE | YES | NULL if status=Open; else opened_date + resolution_days |
| `severity` | INT64 | NO | `1` = critical, `2` = high, `3` = low. Numeric so downstream models can weight/aggregate arithmetically |
| `product_area` | STRING | NO | Compute, Storage, Networking, Auth, API, UI, Billing |
| `status` | STRING | NO | `Open`, `In Progress`, `Resolved`, `Closed` |

Severity distribution target:
- severity 1: 3% · severity 2: 12% · severity 3: 85% (formerly P1 / P2 / (P3+P4) collapsed)

### `account_health` (~50,000 rows)

**Grain:** one row per account per calendar week (52 weeks × ~1,000 accounts ≈ 52,000 rows, trimmed to ~50,000 by dropping pre-contract periods).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `account_id` | STRING | NO | FK → `accounts.account_id` |
| `date` | DATE | NO | week ending date (Sundays) |
| `health_color` | STRING | NO | `Green`, `Yellow`, `Red` |
| `compute_credits_consumed` | INT64 | NO | weekly rollup from `daily_usage_logs` |

Composite PK: `(account_id, date)`.

`health_color` is derived heuristically during generation:
- Green if weekly usage ≥ 15% of monthly allotment AND < 3 open sev-1/2 tickets
- Yellow if weekly usage 5%–15% of monthly allotment OR 3–5 open sev-1/2 tickets
- Red if weekly usage < 5% of monthly allotment OR > 5 open sev-1/2 tickets OR any open sev-1 > 7 days

### `daily_usage_logs` (~200,000 rows)

**Grain:** one row per account per day of usage. Not every account has every day.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `log_id` | STRING | NO | PK; format `LOG-0000001`..`LOG-0200000` |
| `account_id` | STRING | NO | FK → `accounts.account_id` (**violated for ~200 orphan rows**, edge case #5) |
| `date` | DATE | NO | can be outside contract window for ~100 rogue rows |
| `compute_credits_consumed` | INT64 | NO | daily total; distributions per spec 03 |

## Foreign-key integrity policy

| Table | FK | Clean-data policy | Intentional violation |
|---|---|---|---|
| `accounts.rep_id` | → csm_reps.csm_id | 100% valid | none |
| `contracts.account_id` | → accounts | 100% valid | none |
| `support_tickets.account_id` | → accounts | 100% valid | none |
| `account_health.account_id` | → accounts | 100% valid | none |
| `daily_usage_logs.account_id` | → accounts | ~99.9% valid | ~200 rows use random UUIDs (edge #5) |

Downstream metric SQL uses INNER JOINs on `accounts`, which naturally filters
orphans. The QA harness explicitly counts the orphans to prove they exist.

## Column naming decision (`accounts.rep_id` → `csm_reps.csm_id`)

`accounts` uses the column name `rep_id` to preserve the business-side term
("assigned rep"). The referenced PK on `csm_reps` is `csm_id`. This
name-mismatch FK is intentional and common in real-world data models — the
column name reflects the *role* the value plays in the child table (an
account has a rep), while the PK reflects the *entity* it identifies in the
parent table (the CSM).

**Join pattern everywhere in the pipeline:**

```sql
FROM accounts a
JOIN csm_reps  c  ON a.rep_id = c.csm_id
```

dbt tests (`dbt_project/models/staging/_sources.yml`) enforce this
relationship via the built-in `relationships` test:

```yaml
- name: rep_id
  tests:
    - relationships:
        to: source('gcs_raw', 'csm_reps')
        field: csm_id
```

Downstream marts (`mart_csm_avr`) group by `csm_id` since that is the
canonical CSM identifier, not `rep_id`.
