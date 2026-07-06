# Phase 3 Dashboard Report

_Generated: 2026-07-03 — see `dashboard/app.py` and `specs/08-dashboard.md`._

## Summary

| Item | Value |
|---|---|
| Framework | Streamlit 1.50 + Altair 5.5 |
| Total lines | ~360 (`dashboard/app.py`) |
| BigQuery queries per page load | 5–7 (all cached 10 min) |
| Launch command | `make dashboard` → `http://localhost:8501` |
| Auth | Application Default Credentials (same as Phase 1/2) |

## Sections rendered

| # | Section | Chart type | Source |
|---|---|---|---|
| 1 | Headline KPIs | **Two rows, 9 custom-HTML cards** (via `render_kpi_card()`, replaces `st.metric` on 2026-07-04 per exec ask): (a) 4 book KPI cards — Accounts / Annual Recurring Revenue / **AVR Score(avg)** / % Red, each with month-over-month delta; (b) 5 AVR component score cards — **Deployment Score**, **Technical Health Score**, **Consumption Sustainability Score**, **Retention Signal**, **Bookings Realization** — each `AVG(component_score) × 100` at filter-set grain with month-over-month delta. Score cards (AVR Score(avg) + all 5 components) get a **band-colored left border** (Green ≥ 75 / Yellow 50–74 / Red < 50) so exec sees health at a glance; `% Red` also band-colored but with **inverted thresholds** (Green ≤ 25% / Yellow 26–50% / Red > 50%) since lower is better — mirrors the AVR bands around the 50 midpoint via `band_invert=True`. `Accounts` and `Annual Recurring Revenue` render **plain** — no border, no background tint — since they're structural context (book size, revenue base) that don't map to a 0–100 health scale; invisible border preserved for row alignment. **`AVR Score(avg)` is the hero card** — `highlight=True` thickens its border to 10 px, enlarges the value font to 2.6 rem, layers a subtle band-tinted background + soft box-shadow so the composite headline visually dominates the row. Delta arrows are colored explicitly (↑ green good / ↓ red bad / → grey zero); `% Red` uses `delta_lower_is_better=True` so a negative delta reads green. Header placement (rather than leaderboard columns) surfaces the "which lever moved the composite this month?" story next to the composite AVR Score(avg) | `mart_account_avr` |
| 1b | Account detail (single-customer drill-down) | 8 metric cards + horizontal bar chart of 5 AVR components (D/C/T/R/B) | `mart_account_avr` |
| 2 | Purchased vs Consumed | Altair bars (monthly consumed compute credits) + dashed red step-after reference line (monthly purchased allotment). Aggregates the current selection: 0 = book, 1 = single customer, N = sum. Bars above line = expansion signal; bars well below = shelfware risk | `mart_account_avr` + `stg_daily_usage_logs` |
| 3 | Technical Health(Support) | Altair stacked bar of monthly opened support tickets by severity (Sev 1 Critical red `#C62828` / Sev 2 High amber `#F9A825` / Sev 3 Low grey `#90A4AE`), scoped to the **same 12-month rolling window** anchored on the selected Account Snapshot that §2 uses — the two side-by-side charts react consistently to the snapshot picker. Caption shows window range + total tickets + Sev-1 subtotal. Ordinal X-axis with pre-formatted `%b %Y` labels. Chart height 340 px. **Replaces AVR Band stacked bar (2026-07-04)** — the band breakdown is already available at CSM grain in §4 (`#Green/#Yellow/#Red/% Red`) with owner attribution, and the exec question "is technical health deteriorating?" is better answered by leading indicators (ticket volume + severity mix) than the derived AVR band | `stg_support_tickets` (accounts scoped via `mart_account_avr` CTE) |
| 4 | CSM Leaderboard | Sortable dataframe w/ exec-friendly headers (`CSM ID`, `CSM Name`, `Region`, `#Accounts`, `ARR$$`, `Avg AVR Score`, `#Green`, `#Yellow`, `#Red`, `% Red`, `Expansion Oppty`, `Expansion ARR`); `CSM ID` shows numeric-only (`014` not `CSM-014`); `Avg AVR Score` rounded to integer; currency columns uniformly in `$X.XXM`; conditional band coloring on `Avg AVR Score` (75/50 thresholds); 🏆 champion marker on the highest-`Avg AVR Score` row only (semantic, follows the AVR leader on re-sort); auto-narrows to owning CSMs when Customers are selected. **Column rename 2026-07-04**: `Average AVR` → `Avg AVR Score` for symmetry with the new component-score KPI cards (Deployment Score / Technical Health Score / etc.) in the top header — composite + its 5 components read as one "... Score" family. **`Technical Health` column removed 2026-07-04** per exec ask: the T-component story is now told exclusively by the row-2 Technical Health Score KPI card at book grain (§1), which decouples the "which component moved?" diagnostic from CSM attribution and keeps the leaderboard at 12 scan-friendly columns. `mart_csm_avr.avg_technical_health` is retained in the mart for ad-hoc BigQuery use — only the dashboard SELECT was slimmed. **AVR concentration diagnostic** below the table: book-wide footnote comparing `Average AVR` vs `ARR-weighted AVR` (positive gap = biggest accounts healthier; negative = revenue exposed); collapsible expander lists CSMs where `|gap| ≥ 10 pts` (sorted by `|gap|` desc). Rationale for keeping this out of the leaderboard columns: 69% of CSMs agree within 5 pts, would bury signal in noise | `mart_csm_avr` + `mart_account_avr` |
| 5 | Expansion Opportunities | Sortable dataframe, ranked by ARR (raw IDs hidden). **Exec-friendly column headers** (renamed 2026-07-04): `Customer` / `Region` / `Segment` / `Annual Commit$$` / `Days to Renewal` / `AVR Score` / `AVR Health` (the last from raw `band` Green/Yellow/Red). `$$` suffix on the currency column matches the leaderboard `ARR$$` convention. Flag definition lowered on 2026-07-04: `trailing_3mo_usage ≥ 90%` of allotment (was `> 120%`) AND `days_to_renewal ≤ 180`. Surfaces "approaching cap" earlier, not just "already over". **Renewal-window context caption** below the KPI cards shows what fraction of active accounts fall inside the 180-day renewal window on the selected snapshot (structural upper bound on the flagged count) | `mart_account_avr` |
| ~~6~~ | (removed 2026-07-04) | Was "Health & Usage — two charts side-by-side". The **Overall product platform usage** line was retired (redundant with §2 P-vs-C which shows consumption against the purchased baseline). The **Technical Health(Support)** chart was moved into §3 (replacing the retired AVR Band chart) and rescoped from the full 2025-01 → 2026-06 window to the same 12-month rolling window §2 uses | — |

## Filters (sidebar)

- **Customer** — first filter, global list of ~720 customers, type to search. Not cascaded from other filters so the exec can jump straight to any customer.
- **Account Snapshot** — 18 month-ends, `Month YYYY` labels, newest-first (default: latest, June 2026)
- **Region** — AMER · EMEA · APAC · JAPAC
- **CSM** — cascades from Region (50 total)
- **Segment** — Enterprise · Mid-Market (per spec 02)

All filters combine with AND. Selecting a single customer additionally unlocks the Account detail section and switches the trend chart to a per-customer line.

## Smoke-test reconciliation

Direct BQ queries confirm the dashboard's data layer:

| Query | Result | Phase 1/2 reference |
|---|---|---|
| Snapshots available | 18 | Matches `mart_account_avr` grain |
| Regions | AMER, APAC, EMEA, JAPAC | Matches spec 03 |
| Segments | Enterprise, Mid-Market | Matches spec 02 |
| CSMs total | 50 | Matches spec 03 |
| CSMs in EMEA | 18 | 45%/30%/15%/10% weights → ~15±5 for EMEA |
| Accounts on 2026-01-31 (all filters) | 609 | Matches Phase 1 |
| Expansion opps on 2025-11-30 (all filters, peak) | 246 | Data-shape peak — most contracts within 180-day renewal window |
| Expansion opps on 2026-06-30 (all filters, default) | 4 | 41 of 194 active accounts have dtr ≤ 180; approaching-cap cohort hit rate ≈ 10% |
| Annual Recurring Revenue on 2026-01-31 (all filters) | $249.8M | |
| Avg AVR on 2026-01-31 (all filters) | 62.2 | |
| % Red on 2026-01-31 (all filters) | 25.9% | 158 / 609 = 25.9% — matches |

## Synthetic-data regeneration (2026-07-04)

To give the 0.90 expansion threshold visible signal, added a new **cohort #6 —
Approaching Cap** (100 accounts consuming steadily in `[0.90, 1.20)` × allotment
per generator-month, carved from the Normal population). Multi-contract handling
generates usage across base + renewal spans using each contract's own allotment
so renewed accounts keep signal into the second contract year.

Cohort now = 50 Spike & Drop + 100 Shelfware + 150 Overages + 30 Expansions +
100 Approaching Cap = **430 special / 570 normal** (was 330 / 670). New EC-6 QA
assertion: ≥ 70 accounts with ≥ 6 calendar months in `[0.80, 1.20)` × allotment
(band widened from generator's `[0.90, 1.20)` to absorb month-boundary bleeding).
**All 26 QA checks pass, actual EC-6 = 103.**

Section 5 flagged-count sweep across snapshots (post-regen):

| Snapshot | Active | Flagged | Flagged ARR |
|---|---:|---:|---:|
| 2025-07-31 | 1000 | 124 | $41.24M |
| 2025-08-31 | 1000 | 215 | $77.57M |
| 2025-09-30 | 1000 | 233 | $84.43M |
| 2025-10-31 | 1000 | 240 | $87.58M |
| 2025-11-30 | 1000 | **246** | **$91.83M** |
| 2025-12-31 | 1000 | 244 | $91.64M |
| 2026-01-31 | 609 | 123 | $51.95M |
| 2026-02-28 | 284 | 34 | $15.58M |
| 2026-06-30 (default) | 194 | 4 | $0.49M |

The Jun 2026 default is inherently sparse — only 41 of 194 active accounts
have a contract renewing within 180 days (contract-end demographic: 714
accounts renewed Jan-Feb 2026, only 48 renew Jul-Dec 2026). A helper caption
in Section 5 surfaces this ratio on every snapshot.

## Data-layer bugs found + fixed during Phase 3

1. **`mart_account_avr` missing `region` column** — original mart had no way to filter by region at account grain. **Fixed** by joining `stg_csm_reps` via `rep_id → csm_id` FK (name-mismatch preserved intentionally) and denormalizing `region` + `csm_name` into the mart.
2. **Spec 08 listed 3 segments (Enterprise/Mid-Market/SMB)** — data-model spec 02 defines only 2. **Fixed** in `specs/08-dashboard.md`.
3. **Column-name drift** — dashboard queried `segment` (should be `account_segment`) and `segment_focus` (doesn't exist on CSM mart; used `csm_name` instead). **Fixed** in `dashboard/app.py`.
4. **Trend UX** — original logic collapsed to a single "All" line when exactly 1 region was selected. **Fixed** to always group by region so 1-region filter shows 1 labelled line rather than an unlabelled aggregate.

Every fix followed the spec-driven workflow: root cause → update spec → update code → verify.

## Cost profile

BigQuery Sandbox limits: 10 GB storage / 1 TB queries/month.
- `mart_account_avr` = 2.4 MB · `mart_csm_avr` = 0.1 MB
- Per page load: ~5 cached queries scanning ≤3 MB each → ~15 MB max
- 10-min cache TTL means an exec refreshing every minute for a full day = ~144 refreshes × 15 MB = 2.16 GB — still 0.2% of the monthly free tier

## Reproduce

```bash
make phase3        # generate → validate → load → dbt-build → dashboard
# or if marts are already built:
make dashboard     # streamlit run dashboard/app.py --server.port 8501
```

Open `http://localhost:8501` — the app renders in <2 s on first load, <500 ms on cached filter changes.

## Scheduler (always-on + daily refresh)

Two macOS `launchd` user-scope jobs give production-like operation without leaving the laptop:

| Label | Trigger | Purpose |
|---|---|---|
| `com.nidaggar.gcs-northstar-dashboard` | RunAtLoad + KeepAlive | Always-on Streamlit on `127.0.0.1:8501` |
| `com.nidaggar.gcs-northstar-refresh` | Daily 9:00 AM PT | Runs `scripts/refresh_dashboard.sh` (dbt build + dashboard kickstart) |

Install and verify:

```bash
make scheduler-install    # bootstrap both jobs (kills any stray :8501 process first)
make scheduler-status     # state + PID + port listener
make scheduler-refresh    # kickstart refresh now + tail logs/refresh-YYYYMMDD.log
make scheduler-uninstall  # bootout both jobs (plists remain on disk)
```

End-to-end validation (2026-07-04): manual kickstart ran dbt build (114 PASS, 2 expected WARN, 0 ERROR in 47 s), then kickstarted the dashboard (PID rotated, HTTP 200 within 5 s). All logs clean.

Plist reference copies live in `scripts/launchd/`; installed copies at `~/Library/LaunchAgents/`.
