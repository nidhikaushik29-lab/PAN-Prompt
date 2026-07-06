# GCS-NorthStar — Account Value Realization (AVR)

Spec-driven prototype of a north-star metric for the Global Customer Services
organisation: **Account Value Realization (AVR)** — one 0–100 score per
account per month, blending five observable-telemetry components.

```
AVR  =  100 × ( 0.20·D  +  0.30·C  +  0.25·T  +  0.15·R  +  0.10·B )
```

| Component | Weight | Signal |
|---|---:|---|
| **D** — Deployment                | 20 % | Onboarding milestones + shelfware penalty (product events) |
| **C** — Consumption Sustainability | 30 % | Sustained usage vs contracted allotment (usage metering) |
| **T** — Technical Health          | 25 % | `health_color` (55 %) × age-weighted sev-1/2/3 ticket load (30 %) × 30-day trend (15 %) |
| **R** — Retention Signal          | 15 % | Historical renewal / churn behaviour (contracts) |
| **B** — Bookings Realization      | 10 % | Time-to-value ramp on new bookings (bookings + product events) |

Bands: Green ≥ 75 · Yellow 50 – 74 · Red < 50. Full definition:
`specs/01-north-star-metric.md`.

**v1.1 — new-logo ramp exclusion.** Accounts inside the first
`ramp_period_days = 90` days of their contract get `avr_score = NULL` and
`band = 'Onboarding'`, and are excluded from the CSM leaderboard
unconditionally. This prevents new-logo accounts from being auto-Red purely
because the D (Deployment) and B (Bookings) components compare telemetry
against a flat allotment from day one. Component scores stay materialized
for audit. The dashboard exposes two independent sidebar toggles
(`Include ramped customers` default ON, `Include ramping customers`
default OFF) so the exec can toggle the tradeoff live. Rationale and
rejected alternatives (multiplicative D, grace-period renormalization,
docs-only) are documented in `specs/01-north-star-metric.md` §
"Known limitations (v1)".

---

## Repository navigation

| Path | What lives here |
|---|---|
| **`data_generation/`** | Python modules that emit the 6-table synthetic B2B SaaS dataset. `main.py` is the orchestrator; one module per table + one `anomalies.py` for the 6 mandated edge cases. Deterministic (`seed = 42`, fixed window 2025-01-01 → 2026-06-30). |
| **`specs/`** | 9 spec-driven design docs (~1,400 lines). Read `00-overview.md` first. Every code file traces to a spec section; every anomaly to a QA assertion. |
| **`pipeline_and_tests/`** | Metric calculation + data-quality tests, split three ways: `bq/` — raw Phase-1 BigQuery loader + the reference `north_star_metric.sql`; `validate/` — 26-assertion Python QA harness that gates the load step; `dbt_project/` — governed materialization (14 dbt models across staging → intermediate → marts, ~122 tests). |
| **`dashboard/`** | Streamlit executive dashboard (`app.py`, ~2,000 lines). Reads from `mart_account_avr` + `mart_csm_avr` in BigQuery. |
| **`reports/`** | Historical evidence from actual runs: QA output, Phase 2 dbt build+test summary, Phase 3 dashboard reconciliation. |
| **`AVR_FORMULAS.txt`** | Quick-reference for the T-component enhanced formula + worked example. |
| **`AVR-Executive-Presentation.pdf`** | 8-slide executive deck: problem framing, AVR definition, dashboard walkthrough, operationalization plan, roadmap. Companion to the live dashboard demo. |

---

## Quick start — three commands

```bash
make setup          # create .venv, install requirements
make generate       # write 6 CSVs to data/raw/ (deterministic)
make validate       # 26 QA assertions -> reports/qa_report.md
```

Nothing above touches Google Cloud. The synthetic data + QA harness are
fully local. The remaining phases (BigQuery load + dbt + dashboard) require
a GCP project.

### Full pipeline (with BigQuery)

```bash
make setup          # Python venv
make bq-auth        # gcloud auth application-default login  (one-time)
make phase2         # generate + validate + load + dbt-build (14 models, ~122 tests)
make dashboard      # Streamlit on http://localhost:8501
```

Or the compact end-to-end:

```bash
make phase3         # phase2 + dashboard
```

---

## BigQuery — reviewer setup

The pipeline is written against a specific GCP project the author created
for this prototype. To point at **your own** project, change three files:

1. **`Makefile`** — line `PROJECT := global-customer-services-gcs`
2. **`pipeline_and_tests/dbt_project/profiles.yml`** — `project:` field
3. **`dashboard/app.py`** — `PROJECT_ID = "global-customer-services-gcs"`

Prerequisites: BigQuery Sandbox is sufficient — no billing enabled required.
Auth uses Application Default Credentials via `gcloud auth
application-default login`.

The dataset names (`gcs_north_star`, `gcs_north_star_stg`,
`gcs_north_star_marts`) are created on first load and can stay as-is.

---

## What the tests actually assert

**Phase 1 QA harness** — `pipeline_and_tests/validate/quality_checks.py`,
26 assertions:

- Row-count bounds per table (accounts 700-800, contracts 1400-1800, …)
- FK integrity across all cross-table joins
- Deterministic recompute (regenerate → byte-identical CSVs)
- The 6 mandated edge cases are actually present (shelfware, ARR spikes,
  overlapping contracts, tickets closed before opened, orphaned usage,
  out-of-window usage)
- Column type + null-rate expectations from `specs/03-generation-rules.md`

Output: `reports/qa_report.md`. Latest run: **26 / 26 PASS**.

**Phase 2 dbt tests** — `pipeline_and_tests/dbt_project/tests/` (12
singular SQL tests) + generic `unique / not_null / accepted_values /
relationships` tests declared in every `models/*/schema.yml`:

- `test_avr_score_range`: every `avr_score ∈ [0, 100]` and every component
  `d/c/t/r/b_score ∈ [0, 1]`
- `test_band_matches_score`: bucketing agrees with the numeric threshold
- `test_csm_technical_health_range`: rolled-up T-component stays in bounds
- `test_snapshot_dates_are_month_ends`: no mid-month drift
- `test_overlapping_contracts_unexpected` + 3 more anomaly-preservation
  tests: injected edge cases are present in the correct row counts
- Contract sanity (`start_date < end_date`), ticket sanity
  (`closed_at ≥ opened_at`), usage sanity (non-negative, in-window,
  no orphans)

Output: `reports/phase2_report.md`. Latest run: **120 / 122 PASS + 2 expected WARN**
(both WARNs documented in the report).

---

## Reproducibility

- **Seed = 42**, fixed window `2025-01-01 → 2026-06-30`
- Two runs on the same commit produce byte-identical CSVs and byte-identical
  dbt materializations
- Dashboard renders byte-identical Altair specs
- **12,967** account-month rows in `mart_account_avr` (18 month-ends × ~720 accounts)

---

## Requirements

- **Python 3.9+** (system Python on macOS is fine; the venv installs everything)
- **Google Cloud SDK** with a project + BigQuery API enabled (Sandbox is enough)
- `gcloud auth application-default login` completed once

Python deps are pinned in `requirements.txt` (installed by `make setup`).
