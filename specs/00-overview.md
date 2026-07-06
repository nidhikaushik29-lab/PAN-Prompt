# Spec 00 — GCS North Star: Overview

## Purpose
Design and prototype a single "North Star" metric for the Global Customer Services
(GCS) organization as it transitions from an upfront Bookings/TCV model to an
ARR + Consumption hybrid. The metric must balance four dimensions:

1. **Initial contract bookings** — was the deal signed and sized?
2. **Deployment depth** — is the customer actually using what they bought?
3. **Technical health** — is the platform stable for this customer (support tickets, health color)?
4. **Sustained lifecycle usage** — is usage stable and trending toward renewal?

## Business questions this project must answer

- What is the health of an account at a point in time?
- What was purchased vs. what has been consumed?
- What is the technical health (support tickets) trend?
- What does "good" look like — and where do we set Green/Yellow/Red bands?

## Scope of Phase 1 (this repo)

| In scope | Out of scope |
|---|---|
| Synthetic B2B SaaS dataset (6 tables) generated deterministically | Real customer data |
| BigQuery Sandbox load (project `global-customer-services-gcs`, dataset `gcs_north_star`) | Production data warehouse |
| Full **Account Value Realization (AVR)** metric definition + reference SQL | Dashboards / Looker / Sheets |
| Data-quality harness that proves all 5 mandated edge cases landed | Executive slide deck |
| End-to-end reproducible run: `make all` | Comp-plan modeling for reps |

## Spec-driven workflow

Every code file references a spec section. Every spec assertion is tested by
`src/validate/quality_checks.py`. Changing the metric weights or edge-case
percentages means editing a spec first, regenerating data, and re-running QA.

```
specs/
├── 00-overview.md              (this file)
├── 01-north-star-metric.md     AVR formula, weights, SQL
├── 02-data-model.md            ERD, columns, types, keys
├── 03-generation-rules.md      Seed, distributions, cadence
├── 04-edge-cases.md            5 anomalies + injection recipes
├── 05-data-quality-tests.md    Assertions + tolerances
└── 06-bigquery-deployment.md   gcloud install, auth, load, DDL
```

## Deliverables at Phase 1 exit

1. `~/GCS-NorthStar/` populated with specs, code, generated CSVs, QA report
2. Six tables loaded into `global-customer-services-gcs.gcs_north_star`
3. `north_star_metric.sql` returning AVR + band + Expansion flag per account per day
4. `data/qa_report.md` documenting every edge case landed correctly
5. Reproducible: `make clean && make all` recreates the entire environment

## Personas for downstream (Phase 2+) consumption

- **VP of Customer Success** — needs a single 0-100 number per account, per day, with drill-down
- **Solutions Consultant / SC leadership** — needs "at-risk vs. expansion-ready" account lists
- **CSM Rep** — needs their book-of-business rolled up plus per-account trend
- **RevOps / Comp analyst** — needs the metric to be attributable to reps for incentive modeling

## Non-goals

- We are **not** trying to replace existing operational health scores mid-flight. AVR is
  the proposed *unifying* metric; existing scores can feed into the T (Technical Health)
  component as inputs.
- AVR is a **leading indicator**, not a financial reporting metric. It does not replace
  ARR, NRR, or GRR.
