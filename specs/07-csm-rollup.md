# Spec 07 — CSM-level Rollup (`mart_csm_avr`)

## Purpose

The account-grain AVR (`mart_account_avr`) answers "how healthy is this
account?". Leadership and comp analysts need the same signal rolled up to a
CSM's **book of business**. This spec defines the aggregation semantics.

## Grain

**One row per `(snapshot_date, csm_id)`.**

Snapshot dates match `mart_account_avr` — month-end from 2025-01-31 through
2026-06-30 (18 snapshots).

> **FK note.** The account table stores the assigned CSM under `rep_id`; the
> parent PK on `csm_reps` is `csm_id`. Every join in this mart is:
> `ON accounts.rep_id = csm_reps.csm_id`. The mart grain uses `csm_id`
> because that is the canonical CSM identifier. See spec 02 §"Column naming
> decision" for rationale.

## Columns

| Column | Type | Definition |
|---|---|---|
| `snapshot_date` | DATE | Month-end scoring date |
| `csm_id` | STRING | FK → `stg_csm_reps.csm_id` |
| `csm_name` | STRING | Denormalized display name |
| `region` | STRING | Denormalized region |
| `n_accounts` | INT64 | Count of accounts in book with active contract on `snapshot_date` |
| `book_arr` | NUMERIC | `SUM(annual_commit_dollars)` across active accounts |
| `avg_avr` | FLOAT64 | Unweighted mean of account AVR scores |
| `arr_weighted_avr` | FLOAT64 | `SUM(annual_commit_dollars * avr_score) / SUM(annual_commit_dollars)` — primary KPI |
| `n_green` | INT64 | `COUNTIF(band = 'Green')` |
| `n_yellow` | INT64 | `COUNTIF(band = 'Yellow')` |
| `n_red` | INT64 | `COUNTIF(band = 'Red')` |
| `pct_red` | FLOAT64 | `n_red / NULLIF(n_accounts, 0)` |
| `n_expansion_opps` | INT64 | `COUNTIF(expansion_flag)` |
| `expansion_pipeline_arr` | NUMERIC | `SUM(annual_commit_dollars) WHERE expansion_flag` — proxy for uplift potential |

## Aggregation semantics

### Why ARR-weighted AVR is the headline

Two CSMs each with 20 accounts averaging AVR = 70 look identical on an
unweighted average. But if CSM-A's Red accounts are $2M contracts and CSM-B's
Red accounts are $50K contracts, CSM-A's book is far more at-risk. The
ARR-weighted score surfaces that. Both are exposed so leadership can see the
gap.

### Handling accounts without an active contract on `snapshot_date`

Accounts drop out of a CSM's book for a snapshot if:
- Contract expired before `snapshot_date` and no renewal exists, OR
- Contract hasn't started yet as of `snapshot_date`

These accounts are excluded from `n_accounts`, `book_arr`, and both average
AVRs. They are **not** counted as Red — they are simply not in the current
book of business.

### Handling CSMs with zero active accounts

A CSM with no active accounts on a `snapshot_date` still gets a row with:
- `n_accounts = 0`
- `book_arr = 0`
- `avg_avr = NULL`, `arr_weighted_avr = NULL`
- All band counts = 0

This preserves the (`snapshot_date`, `csm_id`) grain for time-series queries
without gaps. Downstream consumers must handle NULL AVR gracefully.

## Downstream use cases

| Persona | Query |
|---|---|
| VP CS | `SELECT snapshot_date, AVG(arr_weighted_avr), SUM(book_arr) FROM mart_csm_avr GROUP BY 1 ORDER BY 1` — company-wide health trend |
| CSM leadership | `SELECT csm_name, arr_weighted_avr, n_red, pct_red FROM mart_csm_avr WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM mart_csm_avr) ORDER BY pct_red DESC` — coaching list |
| RevOps / Comp | `SELECT csm_id, AVG(arr_weighted_avr) FROM mart_csm_avr WHERE snapshot_date BETWEEN Q_start AND Q_end GROUP BY 1` — quarterly comp input |
| Solutions Consultant | `SELECT csm_id, n_expansion_opps, expansion_pipeline_arr FROM mart_csm_avr WHERE snapshot_date = current` — SC handoff queue |

## Invariants (tested)

1. `SUM(n_accounts)` across CSMs on any snapshot_date equals the count of
   distinct accounts with an active contract on that date.
2. `n_green + n_yellow + n_red = n_accounts`.
3. `book_arr = SUM(annual_commit_dollars)` of active accounts assigned to
   that CSM on that snapshot.
4. `arr_weighted_avr` is between 0 and 100 (or NULL when `book_arr = 0`).
5. Every `csm_id` in `mart_csm_avr` exists in `stg_csm_reps`.
