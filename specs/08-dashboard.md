# 08 — Executive Dashboard

_Phase 3 of GCS-NorthStar. Depends on Phase 2 marts._

## Purpose

Give a senior GCS executive (VP or Head of Customer Success) a **single-page,
zero-training** view of AVR performance across the book, sliceable by **Region**
and **Sales Rep (CSM)** — the two dimensions they run 1:1s and QBRs against.

The dashboard is deliberately **read-only** and **decision-oriented**: no
account creation, no ticketing, no forecasting model. Every number on screen
must reconcile to a query against `mart_account_avr` or `mart_csm_avr`.

## Personas

| Persona | Frequency | Primary questions |
|---|---|---|
| VP, GCS | Weekly | Where is my book trending? Which regions/CSMs need intervention this month? |
| Regional Director | Weekly | Which of my CSMs are outperforming/underperforming? |
| CSM (self-serve) | Monthly | Which of my accounts is Red? Which are expansion-ready? |

All three personas use the same page — differentiated only by which Region
and CSM filters they apply.

## Technical stack

| Concern | Choice | Rationale |
|---|---|---|
| Framework | **Streamlit** ≥1.36 | Python-native, reuses `.venv`, no Node build step, deploys locally in one command |
| Charts | **Altair** (bundled with Streamlit) | Declarative grammar, aggregates in Vega-Lite so we don't ship raw rows to browser |
| BigQuery client | `google-cloud-bigquery` + ADC | Same client already used by loader; no new auth flow |
| Caching | `@st.cache_data(ttl=600)` | 10-min TTL; execs won't refresh faster than that, keeps BQ scan cost near zero |
| Layout | Single page, top-down | Filter sidebar + 5 vertical sections |

## Data sources

Only two tables:

- `gcs_north_star_marts.mart_account_avr` — 12,967 rows, 2.4 MB
- `gcs_north_star_marts.mart_csm_avr` — 900 rows, 0.1 MB

**Every** dashboard number traces to one of these. If a KPI can't be computed
from the marts, we add a column to the mart (not to the dashboard).

## Filters (sidebar)

| # | Filter | Type | Default | Notes |
|---|---|---|---|---|
| 1 | Customer | multiselect | Empty | **Global list** of every distinct `(account_id, company_name)` from `mart_account_avr` (1,000 rows). Type to search by name. Positioned first because most exec sessions start with "how is _this_ customer doing?" |
| 2 | Account Snapshot | selectbox | Latest month (top of list) | 18 month-end options from `mart_account_avr.snapshot_date`, labeled `Month YYYY` (e.g. "June 2026") and ordered **newest-first** so the current month sits at the top of the dropdown. Help-text calls out that early-window snapshots (Feb–Apr 2025) are ramp-heavy — see Tenure toggles below. |
| 3 | Region | multiselect | Empty (all) | `AMER / EMEA / APAC / JAPAC` |
| 4 | CSM (Sales Rep) | multiselect | Empty (all in selected region(s)) | Cascades — options refresh when Region changes. Displays **CSM name only** (2026-07-04 per exec ask); the raw `csm_id` is appended in parentheses only when the same name is shared by multiple CSMs (dedup mirrors the Customer picker). Header subtitle also uses the name-only form so the ID never surfaces even for collided names. |
| 5 | Segment | multiselect | Empty (all) | `Enterprise / Mid-Market` (per data-model spec 02) |
| 6 | Tenure | 2 checkboxes | `include_ramped = TRUE`, `include_ramping = FALSE` | Ramp-period v1.1 (added 2026-07-05). Independent toggles rather than a radio: sometimes an exec wants both (audit view), often only ramped (default), occasionally only ramping (onboarding-pipeline view). Both OFF triggers a specialized warning. See §Tenure filter below for the full predicate mapping and CSM-leaderboard invariant. |

Filter combination is AND. Empty selection = no filter (equivalent to "All").

**Cascade convention** — filters whose labels are shown in **blue** (`Region`, `CSM`) are part of a cascade: the child's available options are narrowed by the parent's selection. A short caption in the sidebar makes this convention discoverable.

Customer is **not** cascaded from Region/CSM/Segment — it's a flat global picker so the exec can jump straight to a customer without narrowing first.

**Customer picker — display-label dedup**: 1,000 accounts share only 982 distinct company names (Faker's `company()` pool has natural overlap — e.g. "Johnson LLC" appears 3 times as 3 different `account_id`s). To keep the picker unambiguous *and* clean, the label carries an `(A-###)` account-id suffix **only for the 18 names that collide**, leaving the other 964 as plain names.

**Customer picker — snapshot-mismatch error**: Not every customer is active on every snapshot (contracts start / end within the window). Selecting a customer whose contract range doesn't include the current snapshot triggers a specialized warning that shows each selected customer's active range (`first_snapshot → last_snapshot`) and recommends picking a snapshot inside that range — powered by `load_account_active_ranges()`. If the selected customer *is* active on the snapshot but other sidebar filters (Region/CSM/Segment) exclude it, a separate message directs the user to clear those instead of the Customer filter.

**Tenure filter — ramp-period v1.1** (added 2026-07-05):

- **Predicate mapping** (`_tenure_predicate()` in `dashboard/app.py`):
  - Both toggles ON: no filter — every account passes through (audit view)
  - `include_ramped=TRUE, include_ramping=FALSE` (default): `IFNULL(is_ramp_period, FALSE) = FALSE` — only scored accounts
  - `include_ramped=FALSE, include_ramping=TRUE`: `IFNULL(is_ramp_period, FALSE) = TRUE` — onboarding-pipeline view
  - Both toggles OFF: `FALSE` — degenerate. Specialized warning: "Both **Tenure** toggles are OFF — no accounts match. Enable at least one." Followed by `st.stop()`
- **Scope**: applied to every `mart_account_avr` query — `load_kpis`, `load_book_gap`, `load_expansion_opps`, `load_renewal_window_context`, and (via the `filtered_accounts` CTE) the §2/§3 time-series loaders `load_purchased_vs_consumed` / `load_support_tickets_trend`. For the time-series loaders, tenure membership is evaluated at the **selected snapshot** — an account chosen for its Jun 2026 status contributes its FULL 12-month history, not a per-month tenure-scoped slice
- **CSM Leaderboard invariant**: `mart_csm_avr` filters ramping accounts out of ALL aggregations unconditionally (see `WHERE NOT IFNULL(m.is_ramp_period, FALSE)` in the mart's `accounts_snap` CTE). The sidebar Tenure toggles therefore have **no effect** on the leaderboard — a caption note under the table makes this explicit. Rationale: CSM attribution is only meaningful for scored accounts; keeping the mart aggregation simple is worth the small UI inconsistency (documented rather than papered over)
- **Snapshot-picker help text** flags ramp-heavy early-window snapshots (Feb–Apr 2025 are ~100% ramping in the dataset) so an exec picking Feb 2025 with the default toggles doesn't misread the resulting "no accounts match" as a data outage
- **Account detail §1b ramp branch**: when the single-customer drill-down loads a ramping account (`det['is_ramp_period'] = TRUE`), the score-based UI (AVR + Band cards, 5-component bar chart, formula expander) is replaced with an **onboarding-explainer block** — an `st.info` banner citing `day X of 90`, followed by 4+4 contract/ticket cards (Contract age, Days to renewal, Annual commit, Monthly credits · Open sev-1/2/3, Latest health). The banner points to `specs/01 § Known limitations (v1)` so the exec understands *why* the score is suppressed, not just *that* it is. The bar chart + expander are unconditionally hidden during ramp because component scores are populated in the mart for audit only; surfacing them without the composite would create a misleading "these numbers are actionable" signal

## Sections (top-to-bottom)

### 1. Headline KPIs — 4 + 5 cards (two rows)

All 9 cards render as **custom HTML cards with a colored left border** (via `render_kpi_card()`), replacing the native `st.metric` starting 2026-07-04 per exec ask. The border gives an at-a-glance health signal alongside the numeric value:

- **Score cards** (`AVR Score(avg)`, and all 5 component cards in row 2): border color follows the AVR band thresholds — Green ≥ 75, Yellow 50–74, Red < 50, neutral grey if missing. Same 75/50 cutoffs used on the leaderboard columns and the drill-down component bar chart, so a single mental model works everywhere.
- **`% Red`** (added 2026-07-04 per exec ask): also band-colored, but with **inverted thresholds** since lower is better — Green ≤ 25%, Yellow 26–50%, Red > 50%. Thresholds mirror the AVR bands around the 50 midpoint (75/25 = same dividing line — "75% of accounts NOT Red" reads as healthy). Uses `band_invert=True` on `render_kpi_card`.
- **Non-score cards** (`Accounts`, `Annual Recurring Revenue`): rendered **plain** — no visible left border, no background tint (updated 2026-07-04 per exec ask). These are structural context (book size, revenue base) that don't map to a 0–100 health scale, so any color indicator would be misleading and any background tint would make them read as "greyed out / inactive" next to the vibrant score cards. The invisible border is preserved in the box model (`border-left: 6px solid transparent`) so horizontal text alignment with the sibling score cards stays consistent.

**Hero treatment for `AVR Score(avg)`** (added 2026-07-04 per exec ask): the composite card in row 1 gets `highlight=True`, which thickens the border to 10 px (from 6), enlarges the value font to 2.6 rem (from 1.75), layers a subtle band-tinted background (12% alpha of the band color), and adds a soft box-shadow. Rationale: `AVR Score(avg)` is the *composite headline* — the number the exec is here to see — while the surrounding 3 cards are context (book size, revenue base, tail risk). The hero treatment makes the eye land on the composite first, then scan the context, then drop to the 5 component cards below to answer "which lever moved it?". Same column width as the others; hero-ness is signalled by weight and color, not by hijacking layout space.

**Range indicator on `AVR Score(avg)`** (added 2026-07-05 per exec ask): the primary value renders as `NN / 100` — the trailing ` / 100` is desaturated (`rgba(120,120,120,0.65)`) and shrunk to ~55 % of the hero value font (1.4 rem inside a 2.6 rem line), so it reads as a denominator rather than a competing number. Purpose: the 0–100 scale is self-evident at a glance without adding a caption line or tooltip. Suffix suppressed when the value is missing (`—`). The 5 component score cards in row 2 are also 0–100 but currently render plain; extending the same suffix to those cards would be a one-line consistency pass if requested.

Delta arrows are colored explicitly: **↑ green** for good direction, **↓ red** for bad, **→ grey** for zero. `% Red` uses `delta_lower_is_better=True` so a negative delta reads green (matches the previous `delta_color="inverse"` behavior).

**Row 1 — book KPIs (4 cards)**

| KPI | Formula | Border | Source |
|---|---|---|---|
| Accounts | `COUNT(DISTINCT account_id)` | none (plain) | `mart_account_avr` filtered |
| Annual Recurring Revenue | `SUM(annual_commit_dollars)` | none (plain) | `mart_account_avr` filtered, latest active contract per account |
| AVR Score(avg) | `AVG(avr_score)` | band-colored | `mart_account_avr` filtered |
| % Red | `COUNTIF(band='Red') / COUNT(*)` | neutral | `mart_account_avr` filtered |

**Row 2 — 5 AVR component score cards (added 2026-07-04 per exec ask; all band-colored)**

| KPI | Formula | Source |
|---|---|---|
| Deployment Score | `AVG(d_score) × 100` | `mart_account_avr` filtered |
| Technical Health Score | `AVG(t_score) × 100` | `mart_account_avr` filtered |
| Consumption Sustainability Score | `AVG(c_score) × 100` | `mart_account_avr` filtered |
| Retention Signal | `AVG(r_score) × 100` | `mart_account_avr` filtered |
| Bookings Realization | `AVG(b_score) × 100` | `mart_account_avr` filtered |

Each card shows the month-over-month delta vs the prior snapshot ("+2") so the exec sees direction of travel, not just a level. All 5 component cards use `delta_lower_is_better=False` (higher = better for every component).

**Card ordering rationale**: matches the user's specified order (D → T → C → R → B), which surfaces the two "operational" components (Deployment, Technical Health) first, followed by the "commercial" components (Consumption, Retention, Bookings). This differs from the AVR formula order in specs/01 (D → C → T → R → B) — the header ordering optimises for the exec scan pattern, not the mathematical formula.

**Why header placement rather than leaderboard columns**: the 5 components tell the "which lever moved the composite this month?" diagnostic story at the exec/book level. Placing them next to the composite `AVR Score(avg)` on the same page enables direct comparison ("AVR Score dropped 3 pts because T dropped 8 pts and D drifted +1"). All 5 components are deliberately kept at book grain (not per-CSM leaderboard columns) to preserve the leaderboard's scan-friendly 12-column width and keep CSM-level ownership focused on the composite AVR score, where accountability lives.

### 1b. Account detail — 5-component drill-down (single-customer only)
Renders **only when exactly one Customer is selected**. Shows the account's full context:

- **Header row**: AVR score · band · Annual commit · Days to renewal
- **Second row**: Monthly credit allotment · Open sev-1 tickets · Open sev-2 tickets · Open sev-3 tickets · Latest health color
- **Expansion callout** (if `expansion_flag = TRUE` on the snapshot)
- **Horizontal bar chart** of the 5 AVR components (D/C/T/R/B):
  - Each bar 0-100 with the same Green/Yellow/Red threshold coloring
  - Tooltip shows the component, its weight (%), score, and weighted contribution to the composite
  - Ordering: D → C → T → R → B (matches spec 01 formula order)
- **`How is this AVR score calculated?` expander** (collapsed by default, added 2026-07-05 per exec ask): directly beneath the bar chart, click-to-reveal deep-dive that pairs each component's abstract formula with **this account's live values**:
  - One block per component (D / C / T / R / B) showing the formula in inline code, the account's live score, and the weighted contribution in points
  - T block additionally derives `T_color` from `latest_color` (Green=1.0 / Yellow=0.5 / Red=0.0 / missing=0.5) and cites the account's open sev-1 / 2 / 3 ticket counts so the exec can eyeball which of the three T signals (color, tickets, trend) is dragging
  - R block narrates which of the 4 branches fired (`> 180 d` / `60–180 d` / `< 60 d` / expired) based on the live `days_to_renewal` value
  - Reconciliation line at the bottom sums the 5 contributions back to the composite (`AVR = 17.4 + 21.6 + 16.0 + 11.25 + 9.0 = 75.25 → Green`) so the math is auditable end-to-end
  - Closing block calls out the 3 design invariants (D/B capped at 1.0 · missing color = 0.5 · shelfware ceiling ≈ 40) and points to `AVR_FORMULAS.txt` + `specs/01-north-star-metric.md` + `mart_account_avr.sql` for the full reference
  - Implementation note: the interior markdown string is **flush-left** in the source file (see comment at `dashboard/app.py:1156`); Streamlit's markdown parser treats 4+ leading spaces as a fenced code block and would swallow the bold/italic/inline-code formatting otherwise

This section directly answers the primary single-customer question: **"which of the 5 components is driving this customer's overall AVR up or down?"** For example, an account might have a healthy Deployment Depth (D=90) but a poor Consumption Sustainability (C=30) because usage is spiky — the bars make that visible at a glance, the weighted-contribution tooltip explains why one weak component (C, 30% weight) hurts more than another (B, 10% weight), and the formula expander lets the exec verify the exact math without leaving the page.

**Ramp-period branch (v1.1, 2026-07-05)** — when `det['is_ramp_period'] = TRUE` (`days_in_contract < 90`), the score UI above is entirely replaced with an onboarding-explainer block. The header + industry/segment/region/CSM chip render unchanged. Then:

- An `st.info` banner reads `**Onboarding period (day X of 90)** — AVR score is intentionally suppressed during the ramp window. D and B both compare consumption against a flat allotment, without an expected-ramp curve — so a customer hitting typical enterprise-SaaS onboarding benchmarks (20–30 % of allotment in month 1) would score as if they were shelfware. Component scores are still materialised in mart_account_avr for audit; see specs/01-north-star-metric.md § Known limitations (v1).`
- Two 4-card rows carry contract + operational context: **row 1** = Contract age (`X days`), Days to renewal, Annual commit, Monthly credits · **row 2** = Open sev-1, Open sev-2, Open sev-3, Latest health
- A closing caption tells the exec what happens next: `AVR resumes automatically on the first snapshot where days_in_contract ≥ 90. Bar chart + formula expander are hidden during ramp — pick a later snapshot for the scored view.`
- The bar chart, weighted-contribution tooltip, and formula expander are unconditionally hidden — component scores are populated in `mart_account_avr` for audit only, and surfacing them without the composite would create a misleading "these numbers are actionable" signal

The scored-account path (all four score rows, bar chart, expander) is unchanged and rendered inside the `else` branch of the `is_ramp_period` conditional. The formula expander's "Design invariants" section carries a new bullet documenting the ramp-period exclusion.

Data source: single row from `mart_account_avr` at `(snapshot_date, account_id)`. No additional dbt work required — every field the expander needs (`d/c/t/r/b_score`, `latest_color`, `open_sev1/2/3`, `days_to_renewal`, `band`, `is_ramp_period`, `days_in_contract`) is already materialized.

### 2. Purchased vs Consumed — bar chart with reference line
- X: month-end (12 consecutive month-end points, windowed around the selected Account Snapshot — see rolling-window rule below)
- Y: compute credits per month
- **Bars**: `SUM(compute_credits_consumed)` per month, aggregated across the filtered accounts (from `stg_daily_usage_logs`). Blue.
- **Reference line** (dashed red, step-after interpolation): `SUM(included_monthly_compute_credits)` per snapshot across the same accounts (from `mart_account_avr`)
- **Legend** at top of chart labels both series (Consumed / Purchased) so the dashed red line reads unambiguously
- **X-axis labels** forced to `Mon YYYY` (e.g. "Jun 2026") with `labelOverlap=False` + `tickCount=len(pvc)` so Vega can't collapse to bare month names
- **12-bar rolling window** anchored on the selected Account Snapshot:
  - **Default (forward)**: selected snapshot = **first** bar; window extends +11 months forward. Example: pick Feb 2025 → chart shows Feb 2025 → Jan 2026.
  - **Fallback (trailing)**: when the forward window would run past the latest available snapshot, shift the window backward so it always shows 12 buckets **ending at the latest snapshot**. Example: pick Nov 2025 (or the default Jun 2026) → chart shows Jul 2025 → Jun 2026. Caption calls out the shift so the exec knows the anchor moved.
  - **Small dataset guard**: if the total snapshot count is ≤ 12 (won't happen with the current 18-month dataset but keeps the code robust), the window collapses to all available snapshots.
  - The selected Account Snapshot is guaranteed to be inside the window in every case.
- **Aggregation rule** — always sums the current selection:
  - 0 customers selected → book-level view (all accounts in the sidebar filters)
  - 1 customer selected → that single customer's monthly commitment vs consumption
  - N customers selected → sum of the selection
- **Visual reading**: bars above the line = over-consumption (**Expansion signal**); bars well below = **shelfware risk**
- **Step-after line** is deliberate: for the ~30 mid-year-expansion accounts (spec 04 anomaly #4) the allotment steps up mid-window, which is the correct behavior; for a stable customer the line renders flat/horizontal
- Months where both purchased and consumed are zero (e.g. before a single-customer's contract starts) are dropped so the x-axis doesn't waste real estate on empty bars

This section directly answers the primary Q2 business question — **"what's purchased vs consumed?"** — without requiring the exec to translate an AVR score into commercial intuition. The gap between line and bars is the story.

Data sources: `mart_account_avr` (purchased) + `stg_daily_usage_logs` (consumed), joined via `filtered_accounts` CTE built from the same sidebar filters used elsewhere.

### 3. Technical Health(Support) (stacked bar)
Right-hand chart of the §2/§3 pair. Shares the same **12-month rolling window** anchored on the selected Account Snapshot that §2 (Purchased vs Consumed) uses, so the two side-by-side charts react consistently to the snapshot picker.

- Stacked bar of monthly opened support tickets, colored by severity:
  - Sev 1 (Critical) — red `#C62828`
  - Sev 2 (High) — amber `#F9A825`
  - Sev 3 (Low) — neutral grey `#90A4AE`
- X: `LAST_DAY(opened_date, MONTH)`, ordinal encoding with pre-formatted `%b %Y` labels (same anti-drift pattern as §2 P-vs-C); filtered to the same 12-month window as §2
- Y: `COUNT(*)` of tickets, stacked from zero
- Legend: top, sorted Critical → Low
- Caption: window range + month count + total tickets + Sev-1 subtotal for the current filter set
- Chart height: 340 px (matches §2 for visual balance)
- Data: `stg_support_tickets` joined to a `filtered_accounts` CTE built from `mart_account_avr` (same account-scoping pattern as `load_purchased_vs_consumed`); Python-side window filter applied after the query

**Design note — replaces AVR Band stacked bar (2026-07-04)**: this slot previously held an AVR-band stacked bar (Green/Yellow/Red counts across all snapshots). That view was retired because (a) the same band breakdown is available at CSM grain in the §4 leaderboard (`#Green`, `#Yellow`, `#Red`, `% Red`) where it directly attributes ownership, and (b) the executive question "is technical health deteriorating?" is better answered by leading indicators (ticket volume + severity mix) than by the derived AVR band. The Technical Health(Support) chart replaces it in the same slot.

### 4. CSM Leaderboard — table
- Grain: one row per CSM within the filter set (from `mart_csm_avr`)
- Column labels (exec-friendly): `CSM ID`, `CSM Name`, `Region`, `#Accounts`, `ARR$$`, `Avg AVR Score`, `#Green`, `#Yellow`, `#Red`, `% Red`, `Expansion Oppty`, `Expansion ARR`
- **`CSM ID` display**: strip the `CSM-` prefix (e.g. `CSM-014` → `014`); zero-padded numeric keeps lexicographic sort stable
- **`Avg AVR Score` display**: rounded to integer (e.g. `68` not `68.3`) for scan-ability; underlying numeric value is preserved for sort + band coloring. KPI card at top of dashboard is likewise rounded (both value and month-over-month delta). Column was renamed from `Average AVR` → `Avg AVR Score` on 2026-07-04 per exec ask, matching the "... Score" suffix used on the new row of component-score KPI cards (Deployment Score / Technical Health Score / etc.) so the composite and its 5 components read as a coherent family.
- **`Technical Health` column removed 2026-07-04** per exec ask. The T-component story is now told exclusively by the row-2 **Technical Health Score** KPI card at book grain (see §1). Rationale: header placement decouples the "which component moved this month?" diagnostic from CSM attribution (which is what the leaderboard is for). Removing the column also collapses the leaderboard back to a 12-column scan-friendly width. `mart_csm_avr.avg_technical_health` is retained in the mart for ad-hoc BigQuery use — only the dashboard SELECT was slimmed.
- **Currency columns (`ARR$$`, `Expansion ARR`)** always render in `$X.XXM` (no auto K/M/B switching) so the column is uniformly sortable/readable across all rows
- Default sort: `Avg AVR Score` descending
- Conditional formatting: cell background Green/Yellow/Red on the `Avg AVR Score` column
  using the 75/50 thresholds
- **🏆 champion marker**: prefixes the row with the highest `Avg AVR Score` in the current filter set. Semantic (not positional) — follows the AVR leader even when the user re-sorts by another column. Ties surface a trophy on every tied row.
- **When Customers are selected**: narrows the leaderboard to the CSM(s) who own at least one of the selected accounts, so the exec can see the owning CSM's **full book** performance (not just the selected accounts' numbers)

**AVR concentration** (diagnostic under the table)

Two additions that surface the difference between `Average AVR` (each CSM 1 vote) and `ARR-weighted AVR` (bigger books count more) without polluting the main table. Both respect the current sidebar filters and are powered by `load_book_gap()` + `load_csm_gap_details()` helpers.

- **Book-wide footnote** — one-line caption under the leaderboard: `Book-wide (this filter set): Average AVR = X, ARR-weighted AVR = Y (gap = ±Z pts) → interpretation`. Interpretation buckets:
  - `gap ≥ +2` → *bigger accounts are healthier than the book average suggests*
  - `gap ≤ -2` → *bigger accounts are sicker; revenue exposed*
  - `|gap| < 2` → *book is balanced*
- **High-gap expander** — collapsible section titled `CSMs where Average and ARR-weighted AVR disagree (|gap| ≥ 10 pts)` showing a compact table (CSM ID/Name/Region, #Accts, Book ARR, Average AVR, Weighted AVR, Gap) sorted by `|gap|` desc. Threshold constant `AVR_GAP_THRESHOLD_PTS = 10.0`. When empty, shows a caption confirming the two metrics broadly agree.

**Rationale for keeping this out of the main table**: 69% of CSMs agree within 5 pts, only ~10% of CSMs have `|gap| ≥ 10`, and extreme gaps often come from small books (n<5). Adding it as a column would bury the interesting cases in noise; surfacing it as a diagnostic keeps the leaderboard scan-friendly while still making the story available on demand.

### 5. Expansion Opportunities — table
- Grain: one row per `(account_id)` where `expansion_flag = TRUE` in the
  selected snapshot
- Columns (exec-friendly headers, renamed 2026-07-04): `Customer` (`company_name`), `Region` (`region`), `Segment` (`account_segment`), `Annual Commit$$` (`annual_commit_dollars`, `$$` suffix matches the leaderboard convention for currency columns), `Days to Renewal` (`days_to_renewal`), `AVR Score` (`avr_score`), `AVR Health` (`band`; underlying values are Green/Yellow/Red strings). Raw `account_id` / `csm_id` are hidden from the exec view.
- Sort: `Annual Commit$$` DESC (bigger deals first, applied at the SQL level via `annual_commit_dollars DESC`)
- **Flag definition** (from `mart_account_avr`): `trailing_3mo_usage ≥ 90% × (3 × included_monthly_compute_credits) AND days_to_renewal ≤ 180`. Threshold was lowered from `> 120%` on 2026-07-04 per exec ask so the section surfaces "approaching cap" candidates (early warning) alongside true overages. `expansion_flag` is **not** part of the AVR score — it's a separate commercial signal (see spec 01 §Expansion Opportunity Flag).
- **Renewal-window context caption**: below the KPI cards, always render `"{n_renewal_window:,} of {n_active:,} active accounts ({pct:.0f}%) on this snapshot have ≤180 days to renewal — the eligible pool for the expansion flag. This pool shrinks on late-window snapshots as contracts get renewed; navigate to earlier snapshots for a broader view of expansion signal."` Rationale: on late-window snapshots (e.g. Jun 2026 in a Jan 2025 – Jun 2026 window) only ~20% of active accounts have a contract renewing in the next 180 days, so the flagged count is structurally capped — the caption prevents execs misreading a low count as absence of expansion opportunity.

### 6. (removed)
Previously "Health & Usage — two charts side-by-side" (a full-window Technical Health stacked bar + Overall product platform usage line). Retired 2026-07-04:
- The **Overall product platform usage** line was dropped per exec ask (redundant with §2's Purchased vs Consumed, which shows the same consumption signal against the purchased baseline).
- The **Technical Health(Support)** chart was moved into the §3 slot (replacing the retired AVR Band chart) and rescoped from the full 2025-01 → 2026-06 window to the same 12-month rolling window §2 uses, so it aligns with the snapshot picker.

## What we deliberately DO NOT build (yet)

- Drill-through from KPI card → underlying rows (would need session state
  routing; adds complexity without clear ROI for read-only exec)
- Comp-plan overlays — Phase 4 territory
- Forecasted AVR — needs a time-series model, out of scope
- User authentication — dashboard runs on `localhost:8501` behind SSO/VPN;
  productionizing goes through Cloud Run + IAP as a separate phase

## Reproducibility

Given the same commit (marts unchanged), the dashboard renders **byte-identical**
Altair specs and identical DataFrames. The only non-determinism is `st.cache_data`
TTL, which just controls when the query re-runs — not the result.

## Operational

### Interactive launch (foreground)
- `make dashboard` → opens `http://localhost:8501`, Ctrl+C to stop.
- Useful when iterating on `dashboard/app.py` (Streamlit auto-reloads on save).

### Always-on service + daily refresh (launchd)
Two macOS user-scope launchd jobs handle production-like operation:

| Label | Trigger | Purpose |
|---|---|---|
| `com.nidaggar.gcs-northstar-dashboard` | RunAtLoad + KeepAlive | Always-on Streamlit on `127.0.0.1:8501` |
| `com.nidaggar.gcs-northstar-refresh` | StartCalendarInterval Hour=9 Minute=0 | Daily 9:00 AM PT: `dbt build` then kickstart the dashboard so its `@st.cache_data` is fresh |

Plists live at `~/Library/LaunchAgents/`; reference copies are checked into
`scripts/launchd/` for git history. The refresh shell wrapper is
`scripts/refresh_dashboard.sh`; per-run logs go to `logs/refresh-YYYYMMDD.log`,
launchd stdout/err to `logs/{refresh,dashboard}-launchd.{out,err}.log`.

Install / operate:

```bash
make scheduler-install    # bootstrap both jobs, kill any stray :8501 first
make scheduler-status     # show state + PID + port listener
make scheduler-refresh    # kickstart refresh now + tail today's log
make scheduler-logs       # tail refresh + launchd err logs
make scheduler-uninstall  # bootout both jobs (plists remain on disk)
```

The refresh job depends on ADC at `~/.config/gcloud/application_default_credentials.json`.
ADC typically expires after ~7 days of inactivity — refresh it with `make bq-auth`
if `logs/refresh-YYYYMMDD.log` shows a 401 from BigQuery.

### Requirements
- Python 3.9+, ADC configured (`make bq-auth` from Phase 1)
- Cost: ~5 cached BigQuery queries per page load, each scanning ≤3 MB
  (marts are small). Well under BQ Sandbox 1 TB/month cap.
- Daily refresh adds one `dbt build` per day (~15 MB scanned end-to-end).
