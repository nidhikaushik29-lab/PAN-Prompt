# Spec 06 — BigQuery Deployment

## Target environment

- **GCP Project:** `global-customer-services-gcs`
- **Owner:** `nidhi.kaushik29@gmail.com`
- **Dataset:** `gcs_north_star`
- **Location:** `US` (multi-region — required for BQ Sandbox free tier)
- **Table expiration:** **disabled** (`--default_table_expiration=0`) — Sandbox
  default is 60 days; we override so the exec-review dataset persists

## One-time prerequisites (on the developer machine)

```bash
# 1. Install gcloud + bq CLI
brew install --cask google-cloud-sdk

# 2. Initialize and authenticate as the project owner
gcloud init                                     # pick project global-customer-services-gcs
gcloud auth login                               # user auth for gcloud commands
gcloud auth application-default login           # ADC for Python google-cloud-bigquery

# 3. Verify
gcloud config get-value project                 # → global-customer-services-gcs
bq ls                                            # should return without error
```

Automated by `make bq-init`.

## Dataset creation

```bash
bq --location=US mk --dataset \
   --default_table_expiration=0 \
   --description="GCS North Star metric prototype dataset" \
   global-customer-services-gcs:gcs_north_star
```

Automated by `make bq-dataset` (idempotent — silently skips if exists).

## Table schemas

Explicit JSON schemas live under `src/bq/schemas/`, one per table:

- `csm_reps.json`
- `accounts.json`
- `contracts.json`
- `support_tickets.json`
- `account_health.json`
- `daily_usage_logs.json`

Types follow spec 02. Every column is `REQUIRED` except `support_tickets.closed_date`
(`NULLABLE` — open tickets have no close date).

No autodetect. Schema drift caught at load time.

## Loading

`src/bq/load.py` uses the `google-cloud-bigquery` Python client to:

1. Read each CSV from `data/raw/`
2. Load into `gcs_north_star.<table>` with:
   - `WriteDisposition = WRITE_TRUNCATE` (idempotent re-runs)
   - `SourceFormat = CSV`
   - `SkipLeadingRows = 1`
   - Explicit `schema` (loaded from `src/bq/schemas/<table>.json`)
3. Print per-table row counts on success

Automated by `make load`.

## Metric execution

`src/bq/north_star_metric.sql` computes AVR + band + Expansion flag.

`src/bq/run_metric.py`:
1. Runs the metric SQL as a scripted query
2. Prints:
   - Total accounts scored today
   - Distribution of bands (Green/Yellow/Red counts)
   - Top-10 Red accounts (lowest AVR)
   - Top-10 Expansion Opportunities (highest recent overage)
3. Writes results to `data/metric_smoke.md`

Automated by `make metric`.

## Cost budget

BigQuery Sandbox free tier limits:
- 10 GB active storage / month — our dataset ≈ 30 MB, well within
- 1 TB query bytes processed / month — the metric query scans ≤ 300 MB, ~3300 runs/mo before we'd bill

No credit card, no billing exposure.

## Rollback

```bash
bq rm -r -f -d global-customer-services-gcs:gcs_north_star
```

Recreates cleanly via `make bq-dataset && make load`.
