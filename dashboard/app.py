"""GCS Account Value Realization — Executive Dashboard.

Spec: specs/08-dashboard.md
Data: BigQuery tables gcs_north_star_marts.{mart_account_avr, mart_csm_avr}

Launch: `make dashboard`  →  http://localhost:8501
"""
from __future__ import annotations

import warnings

# Silence Python-3.9 EOL noise from google-cloud libs before importing them
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import altair as alt
import pandas as pd
import streamlit as st
from google.cloud import bigquery

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
PROJECT_ID = "global-customer-services-gcs"
DATASET = "gcs_north_star_marts"
STG_DATASET = "gcs_north_star_stg"
ACCOUNT_TBL = f"`{PROJECT_ID}.{DATASET}.mart_account_avr`"
CSM_TBL = f"`{PROJECT_ID}.{DATASET}.mart_csm_avr`"
USAGE_TBL = f"`{PROJECT_ID}.{STG_DATASET}.stg_daily_usage_logs`"
TICKET_TBL = f"`{PROJECT_ID}.{STG_DATASET}.stg_support_tickets`"

BAND_COLORS = {"Green": "#2E7D32", "Yellow": "#F9A825", "Red": "#C62828"}

st.set_page_config(
    page_title="GCS AVR — Executive Dashboard",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# BigQuery client + query helpers
# --------------------------------------------------------------------------
@st.cache_resource
def get_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID, location="US")


@st.cache_data(ttl=600, show_spinner=False)
def load_snapshots() -> list[pd.Timestamp]:
    q = f"SELECT DISTINCT snapshot_date FROM {ACCOUNT_TBL} ORDER BY snapshot_date"
    df = get_client().query(q).to_dataframe()
    return sorted(df["snapshot_date"].tolist())


@st.cache_data(ttl=600, show_spinner=False)
def load_regions() -> list[str]:
    q = f"SELECT DISTINCT region FROM {CSM_TBL} WHERE region IS NOT NULL ORDER BY region"
    return get_client().query(q).to_dataframe()["region"].tolist()


@st.cache_data(ttl=600, show_spinner=False)
def load_segments() -> list[str]:
    q = f"SELECT DISTINCT account_segment FROM {ACCOUNT_TBL} WHERE account_segment IS NOT NULL ORDER BY account_segment"
    return get_client().query(q).to_dataframe()["account_segment"].tolist()


@st.cache_data(ttl=600, show_spinner=False)
def load_csms_for_regions(regions: tuple[str, ...]) -> pd.DataFrame:
    """Cascading CSM dropdown source. Returns csm_id + csm_name + region."""
    where = ""
    params = []
    if regions:
        where = "WHERE region IN UNNEST(@regions)"
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", list(regions)))
    q = f"SELECT DISTINCT csm_id, csm_name, region FROM {CSM_TBL} {where} ORDER BY csm_name"
    job = get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return job.to_dataframe()


@st.cache_data(ttl=600, show_spinner=False)
def load_all_accounts() -> pd.DataFrame:
    """Global Customer picker source.

    Returns every distinct (account_id, company_name) across ALL snapshots so
    the Customer filter can sit at the top of the sidebar without depending on
    any other widget. Sorted alphabetically for scannability.
    """
    q = f"""
    SELECT DISTINCT account_id, company_name
    FROM {ACCOUNT_TBL}
    ORDER BY company_name
    """
    return get_client().query(q).to_dataframe()


@st.cache_data(ttl=600, show_spinner=False)
def load_account_active_ranges(account_ids: tuple[str, ...]) -> pd.DataFrame:
    """First/last snapshot where each account has an active contract.

    Powers the specialized 'not active on selected snapshot' error message so
    the exec knows *which* snapshots would work for the customer they picked.
    """
    if not account_ids:
        return pd.DataFrame(columns=["account_id", "company_name", "first_snapshot", "last_snapshot"])
    q = f"""
    SELECT
      account_id,
      ANY_VALUE(company_name)  AS company_name,
      MIN(snapshot_date)       AS first_snapshot,
      MAX(snapshot_date)       AS last_snapshot
    FROM {ACCOUNT_TBL}
    WHERE account_id IN UNNEST(@ids)
    GROUP BY account_id
    """
    params = [bigquery.ArrayQueryParameter("ids", "STRING", list(account_ids))]
    return (
        get_client()
        .query(q, job_config=bigquery.QueryJobConfig(query_parameters=params))
        .to_dataframe()
    )


def _as_date(x):
    """Normalize date-like inputs to `datetime.date` for BQ ScalarQueryParameter.

    BigQuery `.to_dataframe()` returns DATE columns as `datetime.date`, but
    hard-coded pd.Timestamp values still come through elsewhere. Handle both.
    """
    if hasattr(x, "date") and callable(x.date):
        return x.date()
    return x  # already a datetime.date


def _tenure_predicate(include_ramped: bool, include_ramping: bool) -> str | None:
    """SQL predicate for the sidebar tenure toggles (ramp-period v1.1).

    Returns:
        None if both toggles are ON (no filter needed, pass every row through).
        A ready-to-AND SQL fragment otherwise:
          - only ramped   → `IFNULL(is_ramp_period, FALSE) = FALSE`
          - only ramping  → `IFNULL(is_ramp_period, FALSE) = TRUE`
          - both OFF      → `FALSE` (yields zero rows; caller renders the
                             "no accounts match" warning path)

    `IFNULL(..., FALSE)` guards against any legacy rows where the column
    might be NULL — treats missing as "not ramping" (the safe default that
    keeps established accounts visible under any toggle combination).
    """
    if include_ramped and include_ramping:
        return None
    if include_ramped:
        return "IFNULL(is_ramp_period, FALSE) = FALSE"
    if include_ramping:
        return "IFNULL(is_ramp_period, FALSE) = TRUE"
    return "FALSE"


def _account_filter_clause(
    snapshot,
    regions: list[str],
    csms: list[str],
    segments: list[str],
    accounts: list[str] | None = None,
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> tuple[str, list[bigquery.ArrayQueryParameter | bigquery.ScalarQueryParameter]]:
    clauses = ["snapshot_date = @snapshot"]
    params: list = [bigquery.ScalarQueryParameter("snapshot", "DATE", _as_date(snapshot))]
    if regions:
        clauses.append("region IN UNNEST(@regions)")
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", regions))
    if csms:
        clauses.append("rep_id IN UNNEST(@csms)")
        params.append(bigquery.ArrayQueryParameter("csms", "STRING", csms))
    if segments:
        clauses.append("account_segment IN UNNEST(@segments)")
        params.append(bigquery.ArrayQueryParameter("segments", "STRING", segments))
    if accounts:
        clauses.append("account_id IN UNNEST(@accounts)")
        params.append(bigquery.ArrayQueryParameter("accounts", "STRING", accounts))
    tenure_pred = _tenure_predicate(include_ramped, include_ramping)
    if tenure_pred is not None:
        clauses.append(tenure_pred)
    return " AND ".join(clauses), params


@st.cache_data(ttl=600, show_spinner="Loading KPIs...")
def load_kpis(
    snapshot: pd.Timestamp,
    prior_snapshot: pd.Timestamp | None,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> dict:
    where, params = _account_filter_clause(
        snapshot, list(regions), list(csms), list(segments), list(accounts),
        include_ramped=include_ramped, include_ramping=include_ramping,
    )
    q = f"""
    SELECT
      COUNT(DISTINCT account_id)                                AS n_accounts,
      SUM(annual_commit_dollars)                                AS book_arr,
      AVG(avr_score)                                            AS avg_avr,
      SAFE_DIVIDE(COUNTIF(band = 'Red'), COUNT(*))              AS pct_red,
      COUNTIF(expansion_flag)                                   AS n_expansion_opps,
      SUM(IF(expansion_flag, annual_commit_dollars, 0))         AS expansion_pipeline_arr,
      -- 5 AVR component averages (scaled ×100 to match AVR display convention).
      -- Powers the second row of headline KPI cards (added 2026-07-04). Uses
      -- simple average = each account 1 vote (matches avg_avr), so the 5 cards
      -- plus the composite tell a consistent story at filter-set grain.
      AVG(d_score) * 100                                        AS avg_d,
      AVG(t_score) * 100                                        AS avg_t,
      AVG(c_score) * 100                                        AS avg_c,
      AVG(r_score) * 100                                        AS avg_r,
      AVG(b_score) * 100                                        AS avg_b
    FROM {ACCOUNT_TBL}
    WHERE {where}
    """
    client = get_client()
    cur = client.query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe().iloc[0]

    prior_avg_avr = None
    prior_pct_red = None
    prior_components: dict[str, float | None] = {
        "avg_d": None, "avg_t": None, "avg_c": None, "avg_r": None, "avg_b": None,
    }
    if prior_snapshot is not None:
        pwhere, pparams = _account_filter_clause(
            prior_snapshot, list(regions), list(csms), list(segments), list(accounts),
            include_ramped=include_ramped, include_ramping=include_ramping,
        )
        pq = f"""
        SELECT AVG(avr_score) AS avg_avr,
               SAFE_DIVIDE(COUNTIF(band='Red'), COUNT(*)) AS pct_red,
               AVG(d_score) * 100 AS avg_d,
               AVG(t_score) * 100 AS avg_t,
               AVG(c_score) * 100 AS avg_c,
               AVG(r_score) * 100 AS avg_r,
               AVG(b_score) * 100 AS avg_b
        FROM {ACCOUNT_TBL} WHERE {pwhere}
        """
        prior = client.query(pq, job_config=bigquery.QueryJobConfig(query_parameters=pparams)).to_dataframe().iloc[0]
        prior_avg_avr = float(prior["avg_avr"]) if pd.notna(prior["avg_avr"]) else None
        prior_pct_red = float(prior["pct_red"]) if pd.notna(prior["pct_red"]) else None
        for k in prior_components:
            prior_components[k] = float(prior[k]) if pd.notna(prior[k]) else None

    return {
        "n_accounts": int(cur["n_accounts"]) if pd.notna(cur["n_accounts"]) else 0,
        "book_arr": float(cur["book_arr"]) if pd.notna(cur["book_arr"]) else 0.0,
        "avg_avr": float(cur["avg_avr"]) if pd.notna(cur["avg_avr"]) else None,
        "pct_red": float(cur["pct_red"]) if pd.notna(cur["pct_red"]) else None,
        "n_expansion_opps": int(cur["n_expansion_opps"]) if pd.notna(cur["n_expansion_opps"]) else 0,
        "expansion_pipeline_arr": float(cur["expansion_pipeline_arr"]) if pd.notna(cur["expansion_pipeline_arr"]) else 0.0,
        "prior_avg_avr": prior_avg_avr,
        "prior_pct_red": prior_pct_red,
        # Component scores (filter-set-wide averages, 0-100 scale)
        "avg_d": float(cur["avg_d"]) if pd.notna(cur["avg_d"]) else None,
        "avg_t": float(cur["avg_t"]) if pd.notna(cur["avg_t"]) else None,
        "avg_c": float(cur["avg_c"]) if pd.notna(cur["avg_c"]) else None,
        "avg_r": float(cur["avg_r"]) if pd.notna(cur["avg_r"]) else None,
        "avg_b": float(cur["avg_b"]) if pd.notna(cur["avg_b"]) else None,
        "prior_avg_d": prior_components["avg_d"],
        "prior_avg_t": prior_components["avg_t"],
        "prior_avg_c": prior_components["avg_c"],
        "prior_avg_r": prior_components["avg_r"],
        "prior_avg_b": prior_components["avg_b"],
    }


@st.cache_data(ttl=600, show_spinner="Loading purchased vs consumed...")
def load_purchased_vs_consumed(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> pd.DataFrame:
    """Monthly compute credits purchased (allotment) vs consumed (actual)
    for the current filter set. Aggregated across all selected accounts.

    Columns: month_end (date), purchased_credits, consumed_credits

    Tenure filter (added 2026-07-05): the ramp-period toggles narrow
    membership *at the selected snapshot* — an account whose is_ramp_period
    status on the selected snapshot doesn't match the toggles is excluded.
    Once selected, the account's FULL 12-month history is aggregated (the
    time series is not itself tenure-scoped per month). This matches the
    "look at the book as it stands on this snapshot" persona used everywhere
    else on the page.
    """
    clauses = ["1 = 1"]
    params: list = []
    if regions:
        clauses.append("region IN UNNEST(@regions)")
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", list(regions)))
    if csms:
        clauses.append("rep_id IN UNNEST(@csms)")
        params.append(bigquery.ArrayQueryParameter("csms", "STRING", list(csms)))
    if segments:
        clauses.append("account_segment IN UNNEST(@segments)")
        params.append(bigquery.ArrayQueryParameter("segments", "STRING", list(segments)))
    if accounts:
        clauses.append("account_id IN UNNEST(@accounts)")
        params.append(bigquery.ArrayQueryParameter("accounts", "STRING", list(accounts)))
    where = " AND ".join(clauses)

    tenure_pred = _tenure_predicate(include_ramped, include_ramping)
    tenure_subquery = ""
    if tenure_pred is not None:
        tenure_subquery = (
            f"AND account_id IN (SELECT DISTINCT account_id FROM {ACCOUNT_TBL} "
            f"WHERE snapshot_date = @tenure_snap AND {tenure_pred})"
        )
        params.append(bigquery.ScalarQueryParameter("tenure_snap", "DATE", _as_date(snapshot)))

    q = f"""
    WITH filtered_accounts AS (
        SELECT DISTINCT account_id
        FROM {ACCOUNT_TBL}
        WHERE {where}
        {tenure_subquery}
    ),
    purchased_monthly AS (
        SELECT
            m.snapshot_date                                   AS month_end,
            SUM(m.included_monthly_compute_credits)           AS purchased_credits
        FROM {ACCOUNT_TBL} m
        JOIN filtered_accounts fa USING (account_id)
        GROUP BY 1
    ),
    consumed_monthly AS (
        SELECT
            LAST_DAY(u.date, MONTH)                           AS month_end,
            SUM(u.compute_credits_consumed)                   AS consumed_credits
        FROM {USAGE_TBL} u
        JOIN filtered_accounts fa USING (account_id)
        WHERE u.date BETWEEN DATE '2025-01-01' AND DATE '2026-06-30'
        GROUP BY 1
    )
    SELECT
        COALESCE(p.month_end, c.month_end)         AS month_end,
        IFNULL(p.purchased_credits, 0)             AS purchased_credits,
        IFNULL(c.consumed_credits,  0)             AS consumed_credits
    FROM purchased_monthly p
    FULL OUTER JOIN consumed_monthly c USING (month_end)
    ORDER BY month_end
    """
    df = get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    # Drop months with no activity on either side (e.g. before a single-customer's
    # contract started) so the x-axis doesn't waste real estate on empty bars.
    if not df.empty:
        df = df[(df["purchased_credits"] > 0) | (df["consumed_credits"] > 0)].reset_index(drop=True)
    return df


# --- Support-ticket trend helper --------------------------------------------
# Uses the same "filter accounts via mart, then aggregate raw staging" pattern
# as load_purchased_vs_consumed. Returns the full 2025-01 → 2026-06 series;
# the caller filters to the 12-month rolling window anchored on the selected
# Account Snapshot (same window PvC uses).

SEVERITY_ORDER = ["Sev 1 (Critical)", "Sev 2 (High)", "Sev 3 (Low)"]
SEVERITY_COLORS = {
    "Sev 1 (Critical)": "#C62828",  # red
    "Sev 2 (High)":     "#F9A825",  # amber
    "Sev 3 (Low)":      "#90A4AE",  # neutral grey
}


@st.cache_data(ttl=600, show_spinner="Loading support ticket trend...")
def load_support_tickets_trend(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> pd.DataFrame:
    """Monthly opened support tickets stacked by severity, restricted to
    accounts matching the current sidebar filters. Ticket-open month is the
    natural grain (LAST_DAY(opened_date, MONTH)).

    Columns: month_end (date), severity_label (str), n_tickets (int)

    Tenure filter uses the same "membership at selected snapshot" semantics
    as load_purchased_vs_consumed — see the docstring there.
    """
    clauses = ["1 = 1"]
    params: list = []
    if regions:
        clauses.append("region IN UNNEST(@regions)")
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", list(regions)))
    if csms:
        clauses.append("rep_id IN UNNEST(@csms)")
        params.append(bigquery.ArrayQueryParameter("csms", "STRING", list(csms)))
    if segments:
        clauses.append("account_segment IN UNNEST(@segments)")
        params.append(bigquery.ArrayQueryParameter("segments", "STRING", list(segments)))
    if accounts:
        clauses.append("account_id IN UNNEST(@accounts)")
        params.append(bigquery.ArrayQueryParameter("accounts", "STRING", list(accounts)))
    where = " AND ".join(clauses)

    tenure_pred = _tenure_predicate(include_ramped, include_ramping)
    tenure_subquery = ""
    if tenure_pred is not None:
        tenure_subquery = (
            f"AND account_id IN (SELECT DISTINCT account_id FROM {ACCOUNT_TBL} "
            f"WHERE snapshot_date = @tenure_snap AND {tenure_pred})"
        )
        params.append(bigquery.ScalarQueryParameter("tenure_snap", "DATE", _as_date(snapshot)))

    q = f"""
    WITH filtered_accounts AS (
        SELECT DISTINCT account_id
        FROM {ACCOUNT_TBL}
        WHERE {where}
        {tenure_subquery}
    )
    SELECT
        LAST_DAY(t.opened_date, MONTH)                    AS month_end,
        CASE t.severity
            WHEN 1 THEN 'Sev 1 (Critical)'
            WHEN 2 THEN 'Sev 2 (High)'
            WHEN 3 THEN 'Sev 3 (Low)'
        END                                               AS severity_label,
        COUNT(*)                                          AS n_tickets
    FROM {TICKET_TBL} t
    JOIN filtered_accounts fa USING (account_id)
    WHERE t.opened_date BETWEEN DATE '2025-01-01' AND DATE '2026-06-30'
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    return get_client().query(
        q, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).to_dataframe()


@st.cache_data(ttl=600, show_spinner="Loading CSM leaderboard...")
def load_csm_leaderboard(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    accounts: tuple[str, ...],
) -> pd.DataFrame:
    """CSM leaderboard.

    When `accounts` is non-empty, narrows to the CSMs that own at least one of
    the selected accounts (so the exec sees the owning-CSM's full book, not
    just the selected accounts' ARR).
    """
    clauses = ["snapshot_date = @snapshot", "n_accounts > 0"]
    params: list = [bigquery.ScalarQueryParameter("snapshot", "DATE", _as_date(snapshot))]
    if regions:
        clauses.append("region IN UNNEST(@regions)")
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", list(regions)))
    if csms:
        clauses.append("csm_id IN UNNEST(@csms)")
        params.append(bigquery.ArrayQueryParameter("csms", "STRING", list(csms)))
    if accounts:
        clauses.append(
            f"csm_id IN (SELECT DISTINCT rep_id FROM {ACCOUNT_TBL} "
            "WHERE snapshot_date = @snapshot AND account_id IN UNNEST(@accounts))"
        )
        params.append(bigquery.ArrayQueryParameter("accounts", "STRING", list(accounts)))
    where = " AND ".join(clauses)
    q = f"""
    SELECT
      csm_id, csm_name, region,
      n_accounts, book_arr,
      ROUND(avg_avr, 1)              AS avg_avr,
      n_green, n_yellow, n_red,
      ROUND(pct_red * 100, 1) AS pct_red,
      n_expansion_opps,
      expansion_pipeline_arr
    FROM {CSM_TBL}
    WHERE {where}
    ORDER BY avg_avr DESC
    """
    return get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()


# --- AVR gap analysis (Average vs ARR-Weighted) -----------------------------
# Two helpers powering the "AVR concentration" footnote + expander under the
# CSM Leaderboard. Both respect the current sidebar filters. Rationale for
# keeping this as diagnostic (rather than a leaderboard column):
# specs/08-dashboard.md §4 → "AVR concentration".

AVR_GAP_THRESHOLD_PTS = 10.0  # per-CSM |gap| considered "big story"


@st.cache_data(ttl=600, show_spinner="Loading book-wide AVR gap...")
def load_book_gap(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> dict | None:
    """Book-wide Average AVR vs ARR-Weighted AVR for the current filter set.
    Returns None if no accounts match; otherwise a dict with:
      n_accounts, total_arr, avg_avr, weighted_avr, gap (weighted − avg).
    """
    where, params = _account_filter_clause(
        snapshot, list(regions), list(csms), list(segments), list(accounts),
        include_ramped=include_ramped, include_ramping=include_ramping,
    )
    q = f"""
    SELECT
      COUNT(*)                                                   AS n_accounts,
      SUM(annual_commit_dollars)                                 AS total_arr,
      AVG(avr_score)                                             AS avg_avr,
      SAFE_DIVIDE(
        SUM(annual_commit_dollars * avr_score),
        SUM(annual_commit_dollars)
      )                                                          AS weighted_avr
    FROM {ACCOUNT_TBL}
    WHERE {where}
    """
    df = get_client().query(
        q, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).to_dataframe()
    if df.empty or pd.isna(df.iloc[0]["avg_avr"]):
        return None
    r = df.iloc[0]
    avg = float(r["avg_avr"])
    wgt = float(r["weighted_avr"]) if pd.notna(r["weighted_avr"]) else None
    return {
        "n_accounts":   int(r["n_accounts"]),
        "total_arr":    float(r["total_arr"]) if pd.notna(r["total_arr"]) else 0.0,
        "avg_avr":      round(avg, 1),
        "weighted_avr": round(wgt, 1) if wgt is not None else None,
        "gap":          round(wgt - avg, 1) if wgt is not None else None,
    }


@st.cache_data(ttl=600, show_spinner="Loading per-CSM AVR gap details...")
def load_csm_gap_details(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    accounts: tuple[str, ...],
    min_abs_gap: float = AVR_GAP_THRESHOLD_PTS,
) -> pd.DataFrame:
    """Per-CSM Average vs ARR-Weighted AVR gap, filtered to CSMs with
    |gap| >= min_abs_gap. Sorted by |gap| descending. Same customer-narrowing
    semantics as load_csm_leaderboard (when accounts is non-empty, narrows to
    the CSMs that own at least one of the selected accounts).
    """
    clauses = [
        "snapshot_date = @snapshot",
        "n_accounts > 0",
        "arr_weighted_avr IS NOT NULL",
    ]
    params: list = [bigquery.ScalarQueryParameter("snapshot", "DATE", _as_date(snapshot))]
    if regions:
        clauses.append("region IN UNNEST(@regions)")
        params.append(bigquery.ArrayQueryParameter("regions", "STRING", list(regions)))
    if csms:
        clauses.append("csm_id IN UNNEST(@csms)")
        params.append(bigquery.ArrayQueryParameter("csms", "STRING", list(csms)))
    if accounts:
        clauses.append(
            f"csm_id IN (SELECT DISTINCT rep_id FROM {ACCOUNT_TBL} "
            "WHERE snapshot_date = @snapshot AND account_id IN UNNEST(@accounts))"
        )
        params.append(bigquery.ArrayQueryParameter("accounts", "STRING", list(accounts)))
    where = " AND ".join(clauses)
    q = f"""
    SELECT
      csm_id, csm_name, region, n_accounts,
      book_arr,
      ROUND(avg_avr, 1)                    AS avg_avr,
      ROUND(arr_weighted_avr, 1)           AS weighted_avr,
      ROUND(arr_weighted_avr - avg_avr, 1) AS gap
    FROM {CSM_TBL}
    WHERE {where}
    """
    df = get_client().query(
        q, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).to_dataframe()
    if df.empty:
        return df
    df = df[df["gap"].abs() >= min_abs_gap].copy()
    df = df.sort_values("gap", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=600, show_spinner="Loading expansion opportunities...")
def load_expansion_opps(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> pd.DataFrame:
    where, params = _account_filter_clause(
        snapshot, list(regions), list(csms), list(segments), list(accounts),
        include_ramped=include_ramped, include_ramping=include_ramping,
    )
    q = f"""
    SELECT
      account_id, company_name, rep_id AS csm_id, region, account_segment AS segment,
      annual_commit_dollars,
      days_to_renewal,
      -- INT cast (not just ROUND) so Streamlit's dataframe renderer shows
      -- "52" not "52.0"; matches the integer display convention used on the
      -- top KPI cards, leaderboard Avg AVR Score, and drill-down bar chart.
      SAFE_CAST(ROUND(avr_score, 0) AS INT64) AS avr_score,
      band
    FROM {ACCOUNT_TBL}
    WHERE {where} AND expansion_flag = TRUE
    ORDER BY annual_commit_dollars DESC
    LIMIT 100
    """
    return get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()


@st.cache_data(ttl=600, show_spinner="Loading account details...")
def load_all_filtered_accounts(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> pd.DataFrame:
    """All accounts matching the current filter set on the selected snapshot.

    Same column shape as load_expansion_opps but WITHOUT the expansion_flag
    constraint, plus `days_in_contract` so ramp status is visible per row,
    and the 5 AVR components (D/C/T/R/B) so the exec sees the driving
    factors per account without having to click into §1b for each one.
    Component scores are stored 0-1 in the mart and rescaled ×100 here to
    match the 0-100 display scale used by `avr_score` and the KPI cards.
    Added 2026-07-06 to answer 'which N accounts?' when the aggregate KPIs
    show a count but no per-account list is otherwise visible in the UI
    (e.g. after filtering by a single CSM to see their book of business).
    Ramping accounts have `avr_score = NULL` and `band = 'Onboarding'` but
    component scores stay populated for audit (see specs/01 § v1.1).
    """
    where, params = _account_filter_clause(
        snapshot, list(regions), list(csms), list(segments), list(accounts),
        include_ramped=include_ramped, include_ramping=include_ramping,
    )
    q = f"""
    SELECT
      account_id, company_name, rep_id AS csm_id, region, account_segment AS segment,
      annual_commit_dollars,
      days_in_contract,
      days_to_renewal,
      SAFE_CAST(ROUND(avr_score, 0) AS INT64) AS avr_score,
      SAFE_CAST(ROUND(d_score * 100, 0) AS INT64) AS d_score,
      SAFE_CAST(ROUND(c_score * 100, 0) AS INT64) AS c_score,
      SAFE_CAST(ROUND(b_score * 100, 0) AS INT64) AS b_score,
      SAFE_CAST(ROUND(r_score * 100, 0) AS INT64) AS r_score,
      SAFE_CAST(ROUND(t_score * 100, 0) AS INT64) AS t_score,
      band
    FROM {ACCOUNT_TBL}
    WHERE {where}
    ORDER BY annual_commit_dollars DESC
    LIMIT 500
    """
    return get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()


@st.cache_data(ttl=600, show_spinner="Loading renewal-window context...")
def load_renewal_window_context(
    snapshot: pd.Timestamp,
    regions: tuple[str, ...],
    csms: tuple[str, ...],
    segments: tuple[str, ...],
    accounts: tuple[str, ...],
    include_ramped: bool = True,
    include_ramping: bool = False,
) -> dict:
    """Count active accounts and those renewing within 180 days on the given
    snapshot. Used to contextualize a low Section 5 count on late-window
    snapshots where most contracts have already renewed."""
    where, params = _account_filter_clause(
        snapshot, list(regions), list(csms), list(segments), list(accounts),
        include_ramped=include_ramped, include_ramping=include_ramping,
    )
    q = f"""
    SELECT
      COUNT(*) AS n_active,
      COUNTIF(days_to_renewal <= 180) AS n_renewal_window
    FROM {ACCOUNT_TBL}
    WHERE {where}
    """
    row = get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe().iloc[0]
    return {
        "n_active": int(row["n_active"]) if pd.notna(row["n_active"]) else 0,
        "n_renewal_window": int(row["n_renewal_window"]) if pd.notna(row["n_renewal_window"]) else 0,
    }


@st.cache_data(ttl=600, show_spinner="Loading account detail...")
def load_account_detail(snapshot, account_id: str) -> dict | None:
    """One row from mart_account_avr for the drill-down section."""
    q = f"""
    SELECT
      account_id, company_name, industry, account_segment, region,
      rep_id AS csm_id, csm_name,
      contract_id, contract_type, annual_commit_dollars,
      included_monthly_compute_credits, days_to_renewal,
      days_in_contract, is_ramp_period,
      d_score, c_score, t_score, r_score, b_score,
      open_sev1, open_sev2, open_sev3, latest_color,
      avr_score, band, expansion_flag
    FROM {ACCOUNT_TBL}
    WHERE snapshot_date = @snapshot AND account_id = @account
    """
    params = [
        bigquery.ScalarQueryParameter("snapshot", "DATE", _as_date(snapshot)),
        bigquery.ScalarQueryParameter("account", "STRING", account_id),
    ]
    df = get_client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def fmt_currency(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def fmt_delta(current: float | None, prior: float | None, unit: str = "", decimals: int = 1) -> str | None:
    if current is None or prior is None:
        return None
    delta = current - prior
    return f"{delta:+.{decimals}f}{unit}"


# --------------------------------------------------------------------------
# Custom KPI card with band-color left border (Section 1 header, added
# 2026-07-04 per exec ask). Mirrors Streamlit's native st.metric look
# (label + big value + delta w/ arrow) but adds a 6-px colored left border
# driven by the AVR band thresholds so score cards give an at-a-glance
# health signal alongside the numeric value. Non-score cards (counts,
# currency, rates) get a neutral grey border for visual alignment.
# --------------------------------------------------------------------------
def _band_color(score: float | None, invert: bool = False) -> str:
    """Return the BAND_COLORS entry for a 0-100 score, or neutral grey.

    `invert=True` flips the comparison so LOWER values render Green — used for
    "% Red" style metrics where a low value is good. Thresholds mirror the
    AVR bands around 50: Green ≤ 25, Yellow 26–50, Red > 50. Rationale for the
    mirror: exec already knows "AVR ≥ 75 = Green", so "% Red ≤ 25 = Green"
    reads as the same 75/25 dividing line (75% of accounts NOT Red = healthy).
    """
    if score is None or pd.isna(score):
        return "#B0BEC5"           # neutral (missing data)
    if invert:
        if score <= 25:
            return BAND_COLORS["Green"]
        if score <= 50:
            return BAND_COLORS["Yellow"]
        return BAND_COLORS["Red"]
    if score >= 75:
        return BAND_COLORS["Green"]
    if score >= 50:
        return BAND_COLORS["Yellow"]
    return BAND_COLORS["Red"]


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert `#RRGGBB` → `rgba(r, g, b, alpha)` for tinted backgrounds."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def render_kpi_card(
    container,
    label: str,
    value_str: str,
    delta_str: str | None = None,
    delta_lower_is_better: bool = False,
    band_value: float | None = None,
    band_invert: bool = False,
    highlight: bool = False,
) -> None:
    """Render a KPI card with a colored left border.

    Parameters
    ----------
    container            : streamlit container (e.g. a `st.columns` cell)
    label                : card title, e.g. "Deployment Score"
    value_str            : pre-formatted value string (e.g. "58" or "—")
    delta_str            : pre-formatted delta from `fmt_delta`, or None
    delta_lower_is_better: True for metrics like `% Red` where a negative
                            delta is "good" (green arrow). Default False.
    band_value           : if provided (0-100 score), border uses AVR band
                            color (Green ≥75 / Yellow 50–74 / Red <50).
                            If None, border is neutral grey — used for
                            non-score cards (Accounts, ARR) that
                            aren't on the 0–100 AVR scale at all.
    band_invert          : flip band thresholds so LOWER = Green. Used for
                            `% Red`: thresholds mirror AVR around 50
                            (Green ≤ 25 / Yellow 26–50 / Red > 50).
    highlight            : hero treatment for the composite AVR Score(avg)
                            card so it visually dominates the row (added
                            2026-07-04 per exec ask). Thickens the border
                            (10px), enlarges the value font (2.6rem), and
                            layers a subtle band-tinted background + soft
                            box-shadow so the eye lands on it first. Delta
                            typography is also bumped a touch for balance.
    """
    border_color = (
        _band_color(band_value, invert=band_invert)
        if band_value is not None
        else "#E0E0E0"
    )

    # Style resolution across three modes:
    #   1. highlight=True                  → hero (thick band border + tinted bg + shadow)
    #   2. band_value provided (not hero)  → base (6px band border + subtle bg)
    #   3. band_value is None (plain)      → NO visible border, transparent bg
    #      Rationale (2026-07-04): user asked that structural cards (Accounts,
    #      ARR) render with no indicator AND not look greyed out. The border
    #      stays in the box model as `transparent` so horizontal alignment
    #      with sibling score cards is preserved (text starts at the same X);
    #      background drops to transparent so no muted rectangle appears.
    _plain = (band_value is None) and (not highlight)

    if highlight:
        border_w   = "10px"
        border_col = border_color
        value_size = "2.6rem"
        delta_size = "0.95rem"
        bg         = _hex_to_rgba(border_color, 0.12)
        shadow     = "box-shadow: 0 2px 6px rgba(0,0,0,0.08);"
        min_h      = "116px"
        pad        = "14px 18px"
    elif _plain:
        border_w   = "6px"
        border_col = "transparent"           # invisible — no indicator
        value_size = "1.75rem"
        delta_size = "0.85rem"
        bg         = "transparent"           # no grey-out
        shadow     = ""
        min_h      = "96px"
        pad        = "10px 14px"
    else:
        border_w   = "6px"
        border_col = border_color
        value_size = "1.75rem"
        delta_size = "0.85rem"
        bg         = "rgba(0,0,0,0.03)"
        shadow     = ""
        min_h      = "96px"
        pad        = "10px 14px"

    # Delta arrow + color
    delta_html = ""
    if delta_str:
        if delta_str.startswith("+"):
            is_positive = True
        elif delta_str.startswith("-"):
            is_positive = False
        else:
            is_positive = None                    # zero
        if is_positive is None:
            delta_color = "#616161"; arrow = "→"
        else:
            is_good = (is_positive != delta_lower_is_better)  # XOR
            delta_color = "#2E7D32" if is_good else "#C62828"
            arrow = "↑" if is_positive else "↓"
        delta_html = (
            f'<div style="color:{delta_color};font-size:{delta_size};'
            f'margin-top:4px;font-weight:500">{arrow}&nbsp;{delta_str}</div>'
        )

    # NOTE: HTML below is emitted with NO leading whitespace on any line —
    # Streamlit's `st.markdown` parser interprets any line indented by 4+
    # spaces as an indented code block, at which point `unsafe_allow_html`
    # is bypassed and the raw tag characters (`<`, `>`) leak onto the page
    # as escaped entities. Implicit string concatenation keeps the Python
    # source readable while keeping the emitted HTML left-aligned.
    container.markdown(
        f'<div style="'
        f'border-left:{border_w} solid {border_col};'
        f'padding:{pad};'
        f'background:{bg};'
        f'border-radius:4px;'
        f'min-height:{min_h};'
        f'margin-bottom:4px;'
        f'{shadow}'
        f'">'
        f'<div style="font-size:0.85rem;color:rgba(120,120,120,0.95);'
        f'line-height:1.2">{label}</div>'
        f'<div style="font-size:{value_size};font-weight:600;line-height:1.3;'
        f'margin-top:4px">{value_str}</div>'
        f'{delta_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
st.sidebar.title("Filters")
st.sidebar.caption(
    "All filters are AND. Empty = no filter.\n\n"
    ":blue[**Blue labels**] mark filters that are linked in a cascade — "
    "the child's available options depend on the parent's selection."
)

# --- Customer (first, global — every distinct customer across all snapshots)
account_df = load_all_accounts()
# Faker's company() pool overlaps: ~18 of the 1000 names collide across
# different account_ids (e.g. "Johnson LLC" x3). Append a compact account_id
# suffix ONLY for the collided names so the picker stays clean for 98% of
# customers while remaining unambiguous for the rest.
_name_counts = account_df["company_name"].value_counts()
account_df["display_label"] = account_df.apply(
    lambda r: (
        f"{r['company_name']} ({r['account_id']})"
        if _name_counts[r["company_name"]] > 1
        else r["company_name"]
    ),
    axis=1,
)
account_df = account_df.sort_values("display_label").reset_index(drop=True)

account_options = account_df["account_id"].tolist()
account_label_map = dict(zip(account_df["account_id"], account_df["display_label"]))
account_name_map = account_label_map
_n_dedup = int((_name_counts > 1).sum())
selected_accounts = st.sidebar.multiselect(
    "Customer",
    options=account_options,
    default=[],
    format_func=lambda aid: account_label_map.get(aid, aid),
    help=(
        f"{len(account_options)} total customers. Type to search by name. "
        f"({_n_dedup} names appear multiple times in the dataset — those entries "
        "carry an `(A-###)` account-id suffix so you can tell them apart.) "
        "Pick 1 to see the full account drill-down; pick 2-8 for per-account trends."
    ),
)

# --- Account Snapshot (newest month at top; labels as "Month YYYY")
snapshots = load_snapshots()                          # ascending — canonical order
snapshot_labels = [d.strftime("%B %Y") for d in snapshots]
# Reverse ONLY for widget display so prior_snapshot arithmetic stays correct.
display_indices = list(range(len(snapshots) - 1, -1, -1))
snapshot_idx = st.sidebar.selectbox(
    "Account Snapshot",
    options=display_indices,
    format_func=lambda i: snapshot_labels[i],
    index=0,                                          # first displayed = newest
    help=(
        "Month-end snapshot. Most recent shown first. "
        "Early-window snapshots (Feb–Apr 2025) are ramp-heavy — most accounts "
        "were < 90 days into their contract and carry `band = 'Onboarding'`. "
        "Toggle **Include ramping customers** below to see them counted in "
        "aggregates; leaving it OFF (default) hides them so AVR averages are "
        "computed only over scored accounts."
    ),
)
selected_snapshot = snapshots[snapshot_idx]
prior_snapshot = snapshots[snapshot_idx - 1] if snapshot_idx > 0 else None

# --- Region (parent in the Region -> CSM cascade; blue label)
all_regions = load_regions()
selected_regions = st.sidebar.multiselect(
    ":blue[Region]",
    options=all_regions,
    default=[],
    help="Empty = all regions. Selection narrows the CSM options below.",
)

# --- CSM (child of Region cascade; blue label)
csm_df = load_csms_for_regions(tuple(selected_regions))
csm_options = csm_df["csm_id"].tolist()
# Show CSM name only in the picker (2026-07-04 per user ask — CSM ID adds
# noise for exec users who identify reps by name). Same dedup pattern as
# the Customer picker: append the ID only when the same name is shared by
# multiple CSMs so the option stays unambiguous in the rare collision case.
_csm_name_counts = csm_df["csm_name"].value_counts()
csm_label_map = {
    row["csm_id"]: (
        f"{row['csm_name']} ({row['csm_id']})"
        if _csm_name_counts[row["csm_name"]] > 1
        else row["csm_name"]
    )
    for _, row in csm_df.iterrows()
}
# Name-only map used by the header subtitle so the "CSM: X, Y" chip never
# reveals the ID even for collided names.
csm_name_map = dict(zip(csm_df["csm_id"], csm_df["csm_name"]))
selected_csms = st.sidebar.multiselect(
    ":blue[CSM (Sales Rep)]",
    options=csm_options,
    default=[],
    format_func=lambda cid: csm_label_map.get(cid, cid),
    help=f"{len(csm_options)} CSMs in current region filter (cascades from Region above)",
)

# --- Segment
all_segments = load_segments()
selected_segments = st.sidebar.multiselect(
    "Segment",
    options=all_segments,
    default=[],
)

# --- Tenure (ramp-period v1.1 — two independent toggles).
#
# Rationale: AVR v1 does NOT score accounts younger than 90 days
# (`is_ramp_period = TRUE`). The mart NULLs their `avr_score` and sets
# `band = 'Onboarding'` because D (Deployment) and B (Bookings Realization)
# both measure consumption against a flat allotment — customers hitting
# typical ramp benchmarks (20-30% of allotment in month 1) would score as
# shelfware. See specs/01-north-star-metric.md § Known limitations (v1).
#
# Two toggles instead of a radio because the exec view is "which populations
# do I want in aggregate stats today?" — sometimes both (audit view), often
# only ramped (default), occasionally only ramping (onboarding pipeline view).
# Defaults: `include_ramped = TRUE`, `include_ramping = FALSE` — matches the
# mart's own default aggregation stance (mart_csm_avr excludes ramping
# accounts unconditionally; see the WHERE clause in mart_csm_avr.sql).
st.sidebar.markdown("**Tenure**")
include_ramped = st.sidebar.checkbox(
    "Include ramped customers (≥ 90 days in contract)",
    value=True,
    help="Fully-onboarded accounts. AVR score is computed and included in aggregates.",
)
include_ramping = st.sidebar.checkbox(
    "Include ramping customers (< 90 days, unscored)",
    value=False,
    help=(
        "New-logo accounts in the 90-day onboarding window. `avr_score = NULL` "
        "and `band = 'Onboarding'` in the mart; they contribute to Accounts / ARR "
        "counts when included but are excluded from all AVR averages regardless. "
        "CSM Leaderboard is unaffected — mart_csm_avr excludes ramping accounts "
        "unconditionally for cost/simplicity reasons."
    ),
)

st.sidebar.divider()
st.sidebar.caption(
    f"**Data source**\n\n`{DATASET}.mart_account_avr` (12,967 rows) + "
    f"`mart_csm_avr` (900 rows)\n\nQueries cached for 10 min."
)
st.sidebar.markdown(
    "<div style='font-size: 0.875em; line-height: 1.5; color: rgba(49, 51, 63, 0.6); margin-top: 0.5rem;'>"
    "<strong style='color: rgba(49, 51, 63, 0.85);'>AVR band thresholds</strong><br>"
    f"<span style='color:{BAND_COLORS['Green']};font-weight:600;'>Green</span> &ge; 75 &nbsp;&middot;&nbsp; "
    f"<span style='color:{BAND_COLORS['Yellow']};font-weight:600;'>Yellow</span> 50&ndash;74 &nbsp;&middot;&nbsp; "
    f"<span style='color:{BAND_COLORS['Red']};font-weight:600;'>Red</span> &lt; 50"
    "</div>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("GCS Account Value Realization")
subtitle_bits = []
if selected_accounts:
    if len(selected_accounts) <= 3:
        names = [account_name_map.get(aid, aid) for aid in selected_accounts]
        subtitle_bits.append(f"Customer: **{', '.join(names)}**")
    else:
        subtitle_bits.append(f"Customer: **{len(selected_accounts)} selected**")
subtitle_bits.append(f"Snapshot: **{selected_snapshot.strftime('%b %Y')}**")
if selected_regions:
    subtitle_bits.append(f"Region: **{', '.join(selected_regions)}**")
if selected_csms:
    # Show names inline if ≤3 selected, else "N selected"
    if len(selected_csms) <= 3:
        names = [csm_name_map.get(cid, cid) for cid in selected_csms]
        subtitle_bits.append(f"CSM: **{', '.join(names)}**")
    else:
        subtitle_bits.append(f"CSM: **{len(selected_csms)} selected**")
if selected_segments:
    subtitle_bits.append(f"Segment: **{', '.join(selected_segments)}**")
st.caption(" · ".join(subtitle_bits))

# --------------------------------------------------------------------------
# Section 1 — Headline KPIs
# --------------------------------------------------------------------------
kpis = load_kpis(
    selected_snapshot,
    prior_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)

if kpis["n_accounts"] == 0:
    # Ramp-period v1.1 (2026-07-05): specialized message for the degenerate
    # "both tenure toggles OFF" state — the predicate resolves to `FALSE` and
    # every downstream query returns zero rows. Distinct from the "filters
    # exclude everything" case because the fix is different (flip a toggle,
    # not narrow filters).
    if not include_ramped and not include_ramping:
        st.warning(
            "Both **Tenure** toggles are OFF — no accounts match. "
            "Enable at least one of *ramped* / *ramping* in the sidebar."
        )
        st.stop()
    if selected_accounts:
        # Specialize the message: tell the exec *why* their pick returned zero
        # rows. Two subcases:
        #   (a) Selected customer(s) simply not active on this snapshot
        #   (b) Selected customer(s) are active, but other sidebar filters
        #       (Region / CSM / Segment / Tenure) exclude them
        ranges = load_account_active_ranges(tuple(selected_accounts))
        snap_d = pd.Timestamp(selected_snapshot).date()
        if not ranges.empty:
            ranges["first_snapshot"] = pd.to_datetime(ranges["first_snapshot"])
            ranges["last_snapshot"] = pd.to_datetime(ranges["last_snapshot"])
            active_on_snap = ranges[
                (ranges["first_snapshot"].dt.date <= snap_d)
                & (ranges["last_snapshot"].dt.date >= snap_d)
            ]
        else:
            active_on_snap = ranges

        if ranges.empty:
            st.warning(
                "Selected customer(s) have no data anywhere in the mart. "
                "This shouldn't happen — contact the data team."
            )
        elif active_on_snap.empty:
            snap_str = selected_snapshot.strftime("%B %Y")
            lines = [f"Selected customer(s) are not active on **{snap_str}**:", ""]
            for _, r in ranges.iterrows():
                label = account_label_map.get(r["account_id"], r["account_id"])
                first = r["first_snapshot"].strftime("%b %Y")
                last = r["last_snapshot"].strftime("%b %Y")
                lines.append(f"- **{label}** — active {first} → {last}")
            lines.append("")
            lines.append(
                "Pick an **Account Snapshot** in the active range, "
                "or clear the Customer filter."
            )
            st.warning("\n".join(lines))
        else:
            tenure_hint = (
                " If the customer is a new logo (< 90 days in contract), also try "
                "enabling **Include ramping customers** in the Tenure section."
                if not include_ramping else ""
            )
            st.warning(
                "Selected customer(s) don't match the other sidebar filters. "
                "Try clearing **Region / CSM / Segment**." + tenure_hint
            )
    else:
        st.warning(
            "No accounts match the current filters. Broaden your selection in the sidebar."
        )
    st.stop()

k1, k2, k3, k4 = st.columns(4)
render_kpi_card(k1, "Accounts", f"{kpis['n_accounts']:,}")
render_kpi_card(k2, "Annual Recurring Revenue", fmt_currency(kpis["book_arr"]))
render_kpi_card(
    k3,
    "AVR Score(avg)",
    # Range indicator: append a muted "/ 100" after the numeric value so the
    # 0-100 scale is self-evident on the hero card without adding a caption
    # line. Sized ~55% of the hero value font and desaturated so it reads as
    # a denominator, not as a competing number. Suppressed when the value is
    # missing ("—") since "— / 100" would look nonsensical.
    # NOTE: the 5 component score cards below (Deployment, Technical Health,
    # Consumption Sustainability, Retention Signal, Bookings Realization)
    # are ALSO on the 0-100 scale — kept plain here per user's targeted ask;
    # extend the same suffix to those cards if a consistency pass is wanted.
    (
        f"{kpis['avg_avr']:.0f}"
        "<span style=\"color:rgba(120,120,120,0.65);font-size:1.4rem;"
        "font-weight:400;margin-left:0.35rem;letter-spacing:-0.01em\">"
        "/ 100</span>"
    ) if kpis["avg_avr"] is not None else "—",
    delta_str=fmt_delta(kpis["avg_avr"], kpis["prior_avg_avr"], decimals=0),
    band_value=kpis["avg_avr"],
    highlight=True,   # hero card: composite headline — visually dominates row 1
)
render_kpi_card(
    k4,
    "% Red",
    f"{kpis['pct_red']*100:.1f}%" if kpis["pct_red"] is not None else "—",
    delta_str=fmt_delta(
        (kpis["pct_red"] or 0) * 100,
        (kpis["prior_pct_red"] or 0) * 100 if kpis["prior_pct_red"] is not None else None,
        unit=" pp",
    ),
    delta_lower_is_better=True,  # lower %Red is better
    band_value=(kpis["pct_red"] * 100) if kpis["pct_red"] is not None else None,
    band_invert=True,            # mirror bands: Green ≤ 25 / Yellow 26–50 / Red > 50
)

# Second row — 5 AVR component score cards (added 2026-07-04 per exec ask).
# Order matches the user's request: Deployment, Technical Health, Consumption
# Sustainability, Retention Signal, Bookings Realization. Each shows the
# filter-set-wide AVG(component_score) × 100 with month-over-month delta and a
# 6-px colored left border (Green ≥75 / Yellow 50–74 / Red <50). Higher = better
# for every component, so no delta_lower_is_better inversion.
# Rationale for header placement rather than leaderboard columns: components
# tell the "which lever moved this month?" diagnostic story at the exec/book
# level, decoupled from CSM attribution (which stays on the leaderboard).
c1, c2, c3, c4, c5 = st.columns(5)
_component_cards = [
    (c1, "Deployment Score",                 "avg_d"),
    (c2, "Technical Health Score",           "avg_t"),
    (c3, "Consumption Sustainability Score", "avg_c"),
    (c4, "Retention Signal",                 "avg_r"),
    (c5, "Bookings Realization",             "avg_b"),
]
for _col, _label, _key in _component_cards:
    _val   = kpis[_key]
    _prior = kpis[f"prior_{_key}"]
    render_kpi_card(
        _col,
        _label,
        f"{_val:.0f}" if _val is not None else "—",
        delta_str=fmt_delta(_val, _prior, decimals=0),
        band_value=_val,
    )

st.divider()

# --------------------------------------------------------------------------
# Section 1b — Account detail (fires only when exactly 1 customer is picked)
# Shows the 5 AVR component scores (D/C/T/R/B) that drive the headline metric,
# plus contract + health context. See specs/01-north-star-metric.md.
# --------------------------------------------------------------------------
if len(selected_accounts) == 1:
    det = load_account_detail(selected_snapshot, selected_accounts[0])
    if det is None:
        st.info(
            f"Account {selected_accounts[0]} was not active on "
            f"{selected_snapshot.strftime('%Y-%m-%d')}. Try an earlier snapshot."
        )
    else:
        st.subheader(f"Account detail — {det['company_name']}")
        st.caption(
            f"{det['industry']} · {det['account_segment']} · "
            f"{det['region']} · CSM: {det['csm_name']} · "
            f"Contract type: {det['contract_type']}"
        )

        # ------------------------------------------------------------------
        # Ramp-period branch (2026-07-05, v1.1). Ramping accounts have their
        # `avr_score` NULLed at the mart level and `band = 'Onboarding'` —
        # rendering the standard AVR / Band / bar-chart / expander stack for
        # them would either dead-end at "—" or (worse) show component scores
        # that the AVR formula deliberately does NOT summarize. Replace the
        # score UI with an onboarding-explainer block that keeps contract +
        # ticket context (still meaningful during ramp) and points to the
        # spec so the exec knows *why* the score is suppressed.
        # ------------------------------------------------------------------
        if det.get("is_ramp_period"):
            _dic = int(det["days_in_contract"]) if pd.notna(det.get("days_in_contract")) else None
            _dic_str = f"day {_dic} of 90" if _dic is not None else "< 90 days"
            st.info(
                f"**Onboarding period ({_dic_str})** — AVR score is intentionally "
                "suppressed during the ramp window. **D** (Deployment Depth) and **B** "
                "(Bookings Realization) both compare consumption against a flat "
                "allotment, without an expected-ramp curve — so a customer hitting "
                "typical enterprise-SaaS onboarding benchmarks (20–30 % of allotment "
                "in month 1) would score as if they were shelfware. Component scores "
                "are still materialised in `mart_account_avr` for audit; see "
                "`specs/01-north-star-metric.md § Known limitations (v1)`."
            )

            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r1c1.metric(
                "Contract age",
                f"{_dic} days" if _dic is not None else "—",
            )
            r1c2.metric(
                "Days to renewal",
                f"{int(det['days_to_renewal'])}" if pd.notna(det["days_to_renewal"]) else "—",
            )
            r1c3.metric("Annual commit", fmt_currency(det["annual_commit_dollars"]))
            r1c4.metric(
                "Monthly credits",
                f"{int(det['included_monthly_compute_credits']):,}",
            )

            r2c1, r2c2, r2c3, r2c4 = st.columns(4)
            r2c1.metric("Open sev-1", int(det["open_sev1"]))
            r2c2.metric("Open sev-2", int(det["open_sev2"]))
            r2c3.metric("Open sev-3", int(det["open_sev3"]))
            r2c4.metric("Latest health", det["latest_color"] or "—")

            st.caption(
                "AVR resumes automatically on the first snapshot where "
                "`days_in_contract ≥ 90`. Bar chart + formula expander are hidden "
                "during ramp — pick a later snapshot for the scored view."
            )
            st.divider()

        else:
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("AVR score", f"{det['avr_score']:.1f}")
            d2.metric("Band", det["band"])
            d3.metric("Annual commit", fmt_currency(det["annual_commit_dollars"]))
            d4.metric(
                "Days to renewal",
                f"{int(det['days_to_renewal'])}" if pd.notna(det["days_to_renewal"]) else "—",
            )

            d5, d6, d7, d8, d9 = st.columns(5)
            d5.metric("Monthly credits", f"{int(det['included_monthly_compute_credits']):,}")
            d6.metric("Open sev-1", int(det["open_sev1"]))
            d7.metric("Open sev-2", int(det["open_sev2"]))
            d8.metric("Open sev-3", int(det["open_sev3"]))
            d9.metric("Latest health", det["latest_color"] or "—")

            if det["expansion_flag"]:
                st.success(
                    "Flagged as **EXPANSION opportunity** on this snapshot "
                    "(trailing-3mo usage ≥ 90% of allotment AND ≤180 days to renewal)."
                )

            st.caption(
                "**AVR = 0.20·D + 0.30·C + 0.25·T + 0.15·R + 0.10·B** — each component 0–100. "
                "Bar color follows band thresholds (Green ≥75, Yellow 50–74, Red <50)."
            )
            comp = pd.DataFrame(
                [
                    {"component": "D — Deployment Depth",           "weight": 20, "score": det["d_score"] * 100},
                    {"component": "C — Consumption Sustainability", "weight": 30, "score": det["c_score"] * 100},
                    {"component": "T — Technical Health",           "weight": 25, "score": det["t_score"] * 100},
                    {"component": "R — Retention Signal",           "weight": 15, "score": det["r_score"] * 100},
                    {"component": "B — Bookings Realization",       "weight": 10, "score": det["b_score"] * 100},
                ]
            )
            comp["weighted_contribution"] = comp["score"] * comp["weight"] / 100.0
            comp_order = comp["component"].tolist()
            bar = (
                alt.Chart(comp)
                .mark_bar()
                .encode(
                    y=alt.Y("component:N", sort=comp_order, title=None),
                    x=alt.X(
                        "score:Q",
                        scale=alt.Scale(domain=[0, 100]),
                        title="Component score (0-100)",
                    ),
                    color=alt.Color(
                        "score:Q",
                        scale=alt.Scale(
                            type="threshold",
                            domain=[50, 75],
                            range=[
                                BAND_COLORS["Red"],
                                BAND_COLORS["Yellow"],
                                BAND_COLORS["Green"],
                            ],
                        ),
                        legend=None,
                    ),
                    tooltip=[
                        alt.Tooltip("component:N", title="Component"),
                        alt.Tooltip("weight:Q", title="Weight (%)"),
                        alt.Tooltip("score:Q", title="Score", format=".1f"),
                        alt.Tooltip("weighted_contribution:Q", title="Weighted contribution", format=".2f"),
                    ],
                )
                .properties(height=200)
            )
            st.altair_chart(bar, use_container_width=True)

            # ------------------------------------------------------------------
            # Formula reveal — click-to-expand deep dive into the math behind
            # this account's AVR. Uses live values from `det` so the exec sees
            # not just the abstract formula but which levers moved the number.
            # Interior string is intentionally flush-left: Streamlit's markdown
            # parser treats 4+ leading spaces as a fenced code block and would
            # swallow the bold/italic formatting otherwise.
            # ------------------------------------------------------------------
            with st.expander("How is this AVR score calculated?"):
                _contribs = {
                    "D": det["d_score"] * 20.0,
                    "C": det["c_score"] * 30.0,
                    "T": det["t_score"] * 25.0,
                    "R": det["r_score"] * 15.0,
                    "B": det["b_score"] * 10.0,
                }
                _total = sum(_contribs.values())

                _tcolor_map = {"Green": 1.0, "Yellow": 0.5, "Red": 0.0}
                _tcolor_val = _tcolor_map.get(det["latest_color"], 0.5)

                _dtr = det["days_to_renewal"]
                if _dtr is None or pd.isna(_dtr):
                    _r_line = "no active contract on this snapshot → R = 0.00"
                elif _dtr > 180:
                    _r_line = f"{int(_dtr)} days to renewal (> 180) → R = 1.00"
                elif _dtr >= 60:
                    _r_line = f"{int(_dtr)} days to renewal (60–180) → R = 0.75"
                elif _dtr >= 0:
                    _r_line = (
                        f"{int(_dtr)} days to renewal (< 60) → R = 1.00 if no Red "
                        "flash in last 30 d, else **R = 0.25** (retention alarm)"
                    )
                else:
                    _r_line = f"contract expired ({int(_dtr)} d past renewal) → R = 0.00"

                st.markdown(
f"""**D — Deployment Depth · weight 20 %**
`D = min(1.0, credits_last_month / included_monthly_credits)`
This account: **D = {det['d_score']:.2f}** → contribution **{_contribs['D']:.1f} pts**

**C — Consumption Sustainability · weight 30 %** *(highest weight)*
`C = max(0, min(1, 1 − CV(daily_usage_90d)))` where CV = stddev / mean
This account: **C = {det['c_score']:.2f}** → contribution **{_contribs['C']:.1f} pts**
*1.0 = perfectly steady · 0.0 = spike-and-drop · < 10 usage days → C = 0 (safety valve)*

**T — Technical Health · weight 25 %**
`T = 0.55·T_color + 0.30·T_tickets + 0.15·T_trend`
- `T_color`: Green = 1.0 · Yellow = 0.5 · Red = 0.0 · missing = 0.5 (unknown ≠ good)
- `T_tickets = 1 − min(1, age_weighted_load / 4.0)` — sev-1 = 0.50, sev-2 = 0.20, sev-3 = 0.05; age ramps 1× → 2× over 30 d
- `T_trend`: 0.5 = flat month-over-month · 1.0 = big improvement · 0.0 = big deterioration
This account: latest color = **{det['latest_color'] or 'unknown'}** (T_color = {_tcolor_val:.2f}) · open sev-1 / 2 / 3 = **{int(det['open_sev1'])} / {int(det['open_sev2'])} / {int(det['open_sev3'])}**
→ **T = {det['t_score']:.2f}** → contribution **{_contribs['T']:.1f} pts**

**R — Retention Signal · weight 15 %**
`R = 1.00 if > 180 d · 0.75 if 60–180 d · 1.00 or 0.25 if < 60 d (0.25 iff Red in last 30 d) · 0.00 if expired`
This account: {_r_line}
→ **R = {det['r_score']:.2f}** → contribution **{_contribs['R']:.1f} pts**

**B — Bookings Realization · weight 10 %**
`B = min(1.0, credits_ytd_contract / (included_monthly_credits × months_in_contract))`
This account: **B = {det['b_score']:.2f}** → contribution **{_contribs['B']:.1f} pts**
*1.0 = on track vs prorated annual commit — prorated so a 90-day-old contract is judged on 3 months, not 12*

---

**Reconciliation**
`AVR = {_contribs['D']:.1f} + {_contribs['C']:.1f} + {_contribs['T']:.1f} + {_contribs['R']:.1f} + {_contribs['B']:.1f} = {_total:.1f}` → **{det['band']}**

**Design invariants**
- **D and B are capped at 1.0** — overages fire the separate Expansion Opportunity flag, they do not inflate AVR
- **Missing health color defaults to `T_color = 0.5`** — a silently-broken feed cannot inflate scores
- **Shelfware ceiling ≈ 40** — if D = C = B = 0, max AVR = 25·T + 15·R ≈ 40
- **Ramp-period exclusion (v1.1)** — accounts with `days_in_contract < 90` have `avr_score = NULL` and `band = 'Onboarding'`; they never enter aggregations

*Full reference:* `AVR_FORMULAS.txt` · *Design spec:* `specs/01-north-star-metric.md` · *Source SQL:* `dbt_project/models/marts/mart_account_avr.sql`
"""
                )

            st.divider()

# --------------------------------------------------------------------------
# Section 2+3 — Purchased vs Consumed + Technical health
# Both charts share the same 12-month rolling window anchored on the selected
# Account Snapshot (see WINDOW_MONTHS logic below) so the pair reacts
# consistently to the snapshot picker.
# --------------------------------------------------------------------------
pvc = load_purchased_vs_consumed(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)

# 12-bar rolling window anchored on the selected Account Snapshot.
# Default rule: forward window (selected snapshot = first bar, +11 months).
# Fallback: if the forward window would run past the last available snapshot,
# shift the window backward so it always shows 12 buckets ending at the last
# snapshot. The selected snapshot is therefore guaranteed to be inside the
# window; captions flag whenever we had to shift (trailing mode).
WINDOW_MONTHS = 12
_total_snaps = len(snapshots)
_start_idx = snapshot_idx  # ascending index of the user's selection
if _total_snaps <= WINDOW_MONTHS:
    # Dataset shorter than the window — just show every snapshot we have.
    _win_start_idx, _win_end_idx = 0, _total_snaps - 1
else:
    _fwd_end_idx = _start_idx + WINDOW_MONTHS - 1
    if _fwd_end_idx <= _total_snaps - 1:
        # Forward window fits — selected snapshot is the first bar.
        _win_start_idx, _win_end_idx = _start_idx, _fwd_end_idx
    else:
        # Ceiling hit — anchor to the latest snapshot and go back 11 months.
        _win_end_idx = _total_snaps - 1
        _win_start_idx = _win_end_idx - (WINDOW_MONTHS - 1)

window_start = pd.Timestamp(snapshots[_win_start_idx])
window_end   = pd.Timestamp(snapshots[_win_end_idx])
is_trailing  = (_win_start_idx != _start_idx)
n_months     = _win_end_idx - _win_start_idx + 1

if not pvc.empty:
    pvc = pvc.copy()
    pvc["month_end"] = pd.to_datetime(pvc["month_end"])
    pvc = pvc[
        (pvc["month_end"] >= window_start) & (pvc["month_end"] <= window_end)
    ].reset_index(drop=True)

tickets_df = load_support_tickets_trend(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)
if not tickets_df.empty:
    tickets_df = tickets_df.copy()
    tickets_df["month_end"] = pd.to_datetime(tickets_df["month_end"])
    tickets_df = tickets_df[
        (tickets_df["month_end"] >= window_start) & (tickets_df["month_end"] <= window_end)
    ].reset_index(drop=True)

c_left, c_right = st.columns(2)

with c_left:
    st.subheader("Purchased vs Consumed")
    snap_str  = selected_snapshot.strftime("%b %Y")
    start_str = window_start.strftime("%b %Y")
    end_str   = window_end.strftime("%b %Y")
    range_str = f"**{start_str} → {end_str}** ({n_months} months)"
    trailing_note = (
        f" (Selected snapshot **{snap_str}** is within 11 months of the latest "
        f"available data, so the chart is anchored on **{end_str}** and shows "
        "the trailing 12 months ending there.)"
        if is_trailing else ""
    )
    if len(selected_accounts) == 1:
        pvc_caption = (
            f"Monthly compute credits **purchased** (allotment reference line) vs "
            f"**consumed** (bars) for the selected customer — {range_str}. "
            "Bars above the line = over-consumption (expansion signal); "
            "bars well below = shelfware risk."
            + trailing_note
        )
    elif selected_accounts:
        pvc_caption = (
            f"Monthly compute credits **purchased** vs **consumed** — aggregated "
            f"across the {len(selected_accounts)} selected customers — {range_str}."
            + trailing_note
        )
    else:
        pvc_caption = (
            f"Monthly compute credits **purchased** vs **consumed** — aggregated "
            f"across all accounts in the current filter set — {range_str}."
            + trailing_note
        )
    st.caption(pvc_caption)

    if not pvc.empty:
        # Pre-format the month label as a string so the X-axis can use ordinal
        # encoding — each bar gets its own discrete slot with a 1:1 label
        # underneath. This avoids Vega's temporal-tick placement drifting the
        # visible label off-by-one relative to the bar (which happens because
        # bars sit at month-END dates like 2025-02-28 while temporal ticks
        # land on month-STARTs like 2025-03-01).
        pvc = pvc.copy()
        pvc["month_label"] = pvc["month_end"].dt.strftime("%b %Y")
        month_order = pvc["month_label"].tolist()

        # Two-layer chart with a shared color scale so the legend can label both
        # marks. Duplicate the data with a `series` column per layer so the
        # tooltip can still show both purchased & consumed values on any hover.
        pvc_bars = pvc.assign(series="Consumed (actual usage)")
        pvc_line = pvc.assign(series="Purchased (monthly allotment)")
        color_scale = alt.Scale(
            domain=["Consumed (actual usage)", "Purchased (monthly allotment)"],
            range=["#4A90D9", "#C62828"],
        )
        # Ordinal X with explicit sort — one tick per bar, angled labels,
        # labelOverlap=False so Vega can't drop labels when width is tight.
        x_axis = alt.Axis(
            labelAngle=-45,
            labelOverlap=False,
            title=None,
        )
        x_enc = alt.X("month_label:O", sort=month_order, axis=x_axis)
        tooltip = [
            alt.Tooltip("month_label:N", title="Month"),
            alt.Tooltip("purchased_credits:Q", title="Purchased", format=",.0f"),
            alt.Tooltip("consumed_credits:Q", title="Consumed",  format=",.0f"),
        ]
        bars = (
            alt.Chart(pvc_bars)
            .mark_bar(opacity=0.85)
            .encode(
                x=x_enc,
                y=alt.Y("consumed_credits:Q", title="Compute credits / month"),
                color=alt.Color(
                    "series:N",
                    scale=color_scale,
                    legend=alt.Legend(title=None, orient="top", direction="horizontal"),
                ),
                tooltip=tooltip,
            )
        )
        # Step-after line: renders horizontal for constant allotments; steps up
        # for mid-year expansions (spec 04 anomaly #4), which is the correct
        # visual for "purchased" changing over time.
        ref_line = (
            alt.Chart(pvc_line)
            .mark_line(strokeWidth=2, strokeDash=[6, 3], interpolate="step-after")
            .encode(
                x=x_enc,
                y=alt.Y("purchased_credits:Q"),
                color=alt.Color("series:N", scale=color_scale, legend=None),
                tooltip=tooltip,
            )
        )
        chart = (bars + ref_line).properties(height=340).configure_view(strokeWidth=0)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No usage data available for the current filters.")

with c_right:
    st.subheader("Technical Health(Support)")
    if tickets_df.empty:
        st.info("No support tickets in the current window/filter set.")
    else:
        tdf = tickets_df.copy()
        tdf["month_label"] = tdf["month_end"].dt.strftime("%b %Y")
        # Ordinal X-axis (same pattern as Purchased vs Consumed) — guarantees
        # 1:1 bar-to-label mapping and avoids month-end/month-start drift.
        month_order_t = (
            tdf[["month_end", "month_label"]]
            .drop_duplicates()
            .sort_values("month_end")["month_label"]
            .tolist()
        )
        total_tickets = int(tdf["n_tickets"].sum())
        n_sev1 = int(tdf.loc[tdf["severity_label"] == "Sev 1 (Critical)", "n_tickets"].sum())
        st.caption(
            f"Monthly tickets opened by severity across the same "
            f"**{start_str} → {end_str}** window ({n_months} months) — "
            f"**{total_tickets:,}** total, **{n_sev1:,}** Sev 1 (Critical). "
            "Stacked bars, opened-date month."
        )
        chart_t = (
            alt.Chart(tdf)
            .mark_bar(size=16)
            .encode(
                x=alt.X(
                    "month_label:O",
                    sort=month_order_t,
                    title=None,
                    axis=alt.Axis(labelAngle=-40),
                ),
                y=alt.Y("n_tickets:Q", title="Tickets opened", stack="zero"),
                color=alt.Color(
                    "severity_label:N",
                    scale=alt.Scale(
                        domain=SEVERITY_ORDER,
                        range=[SEVERITY_COLORS[s] for s in SEVERITY_ORDER],
                    ),
                    legend=alt.Legend(title="Severity", orient="top"),
                    sort=SEVERITY_ORDER,
                ),
                order=alt.Order("severity_label:N", sort="ascending"),
                tooltip=[
                    alt.Tooltip("month_label:N", title="Month"),
                    alt.Tooltip("severity_label:N", title="Severity"),
                    alt.Tooltip("n_tickets:Q", title="Tickets", format=","),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(chart_t, use_container_width=True)

st.divider()

# --------------------------------------------------------------------------
# Section 4 — CSM Leaderboard
# --------------------------------------------------------------------------
st.subheader("CSM Leaderboard")
if selected_accounts:
    lb_caption = (
        f"Book performance on {selected_snapshot.strftime('%B %Y')} for the "
        "CSM(s) who own at least one of the selected customers. "
        "Numbers reflect each CSM's **full book**, not just the selected accounts. "
        "🏆 = highest Avg AVR Score."
    )
else:
    lb_caption = (
        f"Book performance per CSM on {selected_snapshot.strftime('%B %Y')}. "
        "Sort by clicking a column. Cell color on **Avg AVR Score** follows band "
        "thresholds; 🏆 marks the highest Avg AVR Score in the current filter set."
    )
# Ramp-period v1.1 caveat: `mart_csm_avr` filters ramping accounts out of ALL
# aggregations unconditionally (see WHERE clause in the mart's accounts_snap
# CTE), so leaderboard scores never include them regardless of the sidebar
# Tenure toggles. This is a deliberate simplification — CSM attribution is
# only meaningful for scored accounts.
lb_caption += (
    "  \n_Leaderboard scores always exclude ramping accounts (<90 days in "
    "contract); the sidebar **Tenure** toggles affect only the top KPI cards, "
    "the trend charts, and the Expansion Opportunities table._"
)
st.caption(lb_caption)

csm_lb = load_csm_leaderboard(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_accounts),
)

if csm_lb.empty:
    st.info("No CSMs match the current filters.")
else:
    def color_avr(v):
        if v is None or pd.isna(v):
            return ""
        if v >= 75:
            return f"background-color: {BAND_COLORS['Green']}; color: white;"
        if v >= 50:
            return f"background-color: {BAND_COLORS['Yellow']}; color: black;"
        return f"background-color: {BAND_COLORS['Red']}; color: white;"

    # Rename to exec-friendly headers before styling; keep column order intact.
    # Technical Health column removed 2026-07-04 per exec ask — the T-component
    # story is now told exclusively by the row-2 Technical Health Score header
    # KPI card at book grain (see specs/08-dashboard.md §1). Rationale: header
    # placement decouples the diagnostic "which component moved?" question from
    # CSM attribution, which is what the leaderboard is for. See specs/08 §4.
    LEADERBOARD_COLS = {
        "csm_id":                 "CSM ID",
        "csm_name":               "CSM Name",
        "region":                 "Region",
        "n_accounts":             "#Accounts",
        "book_arr":               "ARR$$",
        "avg_avr":                "Avg AVR Score",
        "n_green":                "#Green",
        "n_yellow":               "#Yellow",
        "n_red":                  "#Red",
        "pct_red":                "% Red",
        "n_expansion_opps":       "Expansion Oppty",
        "expansion_pipeline_arr": "Expansion ARR",
    }
    csm_lb_display = csm_lb.rename(columns=LEADERBOARD_COLS)
    # Strip "CSM-" prefix — zero-padded numeric keeps lexicographic sort stable.
    csm_lb_display["CSM ID"] = (
        csm_lb_display["CSM ID"].astype(str).str.replace("CSM-", "", regex=False)
    )

    # Leaderboard-only $M formatter: unify units across all rows so the column
    # sorts and reads consistently (no mixed K/M/B).
    def fmt_millions(v):
        if v is None or pd.isna(v):
            return "—"
        return f"${v/1e6:.2f}M"

    # Champion trophy: mark the row(s) with the highest AVR score. Semantic
    # (not positional) — follows the AVR leader even if the user re-sorts by
    # another column. Values are pre-rounded at the SQL level (`ROUND(avg_avr,
    # 1)`), so exact float comparison is safe.
    top_avr = csm_lb_display["Avg AVR Score"].max()

    def fmt_avr(v):
        if pd.isna(v):
            return "—"
        if pd.notna(top_avr) and v == top_avr:
            return f"🏆 {v:.0f}"
        return f"{v:.0f}"

    styled = (
        csm_lb_display.style.map(color_avr, subset=["Avg AVR Score"])
        .format(
            {
                "ARR$$":            fmt_millions,
                "Expansion ARR":    fmt_millions,
                "Avg AVR Score":    fmt_avr,
                "% Red":            lambda v: f"{v:.1f}%" if pd.notna(v) else "—",
            }
        )
    )
    st.dataframe(styled, width="stretch", hide_index=True, height=380)

    # ---- AVR concentration diagnostic (book-wide gap + high-gap expander) ----
    # Surfaces the difference between Average AVR (each CSM 1 vote) and
    # ARR-weighted AVR (bigger books count more). Rationale for keeping it out
    # of the leaderboard columns: specs/08-dashboard.md §4.
    _book_gap = load_book_gap(
        selected_snapshot,
        tuple(selected_regions),
        tuple(selected_csms),
        tuple(selected_segments),
        tuple(selected_accounts),
        include_ramped=include_ramped,
        include_ramping=include_ramping,
    )
    if _book_gap is not None and _book_gap["weighted_avr"] is not None:
        gap = _book_gap["gap"]
        avg = _book_gap["avg_avr"]
        wgt = _book_gap["weighted_avr"]
        if gap >= 2:
            interp = "→ **bigger accounts are healthier** than the book average suggests."
        elif gap <= -2:
            interp = "→ **bigger accounts are sicker** than the average suggests; revenue at more risk than the count picture."
        else:
            interp = "→ book is balanced; average and revenue-weighted views agree."
        st.caption(
            f"**Book-wide (this filter set):** Average AVR = **{avg}**, "
            f"ARR-weighted AVR = **{wgt}** (gap = **{gap:+.1f}** pts) {interp}"
        )

    _gap_df = load_csm_gap_details(
        selected_snapshot,
        tuple(selected_regions),
        tuple(selected_csms),
        tuple(selected_accounts),
        min_abs_gap=AVR_GAP_THRESHOLD_PTS,
    )
    with st.expander(
        f"CSMs where Average and ARR-weighted AVR disagree "
        f"(|gap| ≥ {int(AVR_GAP_THRESHOLD_PTS)} pts)  —  "
        f"{len(_gap_df)} CSM{'s' if len(_gap_df) != 1 else ''}",
        expanded=False,
    ):
        if _gap_df.empty:
            st.caption(
                "No CSMs in this filter have a gap ≥ "
                f"{int(AVR_GAP_THRESHOLD_PTS)} pts — the two metrics broadly agree."
            )
        else:
            _gap_display = _gap_df.copy()
            _gap_display["csm_id"] = _gap_display["csm_id"].str.replace("CSM-", "", regex=False)
            _gap_display["book_arr"] = _gap_display["book_arr"].apply(
                lambda v: f"${v/1e6:.2f}M" if pd.notna(v) else "—"
            )
            _gap_display = _gap_display.rename(columns={
                "csm_id":       "CSM",
                "csm_name":     "Name",
                "region":       "Region",
                "n_accounts":   "# Accts",
                "book_arr":     "Book ARR",
                "avg_avr":      "Average AVR",
                "weighted_avr": "Weighted AVR",
                "gap":          "Gap (pts)",
            })
            st.dataframe(_gap_display, width="stretch", hide_index=True)
            st.caption(
                "**Positive gap** = weighted > average → biggest accounts healthier than the CSM's per-account mean. "
                "**Negative gap** = weighted < average → biggest accounts sicker; revenue exposed. "
                "Small books (n<5) can swing large — treat as directional, not definitive."
            )

st.divider()

# --------------------------------------------------------------------------
# Section 5 — Expansion Opportunities
# --------------------------------------------------------------------------
st.subheader("Expansion Opportunities")
st.caption(
    "Accounts flagged for expansion on this snapshot: trailing-3mo usage ≥ 90% of "
    "allotment AND ≤180 days to renewal. Ranked by ARR (largest first). Top 100."
)

exp = load_expansion_opps(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)

# Renewal-window context: on late-window snapshots most contracts have already
# renewed, so the eligible pool for expansion flagging shrinks. Show this
# ratio so a low flagged count is understandable rather than alarming.
rw = load_renewal_window_context(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)

k5, k6 = st.columns(2)
k5.metric("Expansion opportunities", f"{kpis['n_expansion_opps']:,}")
k6.metric("Expansion pipeline ARR", fmt_currency(kpis["expansion_pipeline_arr"]))

if rw["n_active"] > 0:
    pct_rw = 100.0 * rw["n_renewal_window"] / rw["n_active"]
    st.caption(
        f"Renewal-window context: {rw['n_renewal_window']:,} of {rw['n_active']:,} active accounts "
        f"({pct_rw:.0f}%) on this snapshot have ≤180 days to renewal — the eligible pool for the "
        f"expansion flag. This pool shrinks on late-window snapshots as contracts get renewed; "
        f"navigate to earlier snapshots for a broader view of expansion signal."
    )

if exp.empty:
    st.info("No expansion opportunities in the current filter set.")
else:
    exp_display = exp.copy()
    exp_display["annual_commit_dollars"] = exp_display["annual_commit_dollars"].apply(fmt_currency)
    # Hide raw IDs; execs only need company_name to identify the customer.
    exp_display = exp_display.drop(columns=["account_id", "csm_id"], errors="ignore")
    # Exec-friendly column headers (2026-07-04 per user ask). `Annual Commit$$`
    # follows the leaderboard `ARR$$` convention (the `$$` suffix marks the
    # column as currency); `AVR Health` renames the raw `band` string
    # (Green/Yellow/Red) as user-facing "health" language.
    exp_display = exp_display.rename(columns={
        "company_name":          "Customer",
        "region":                "Region",
        "segment":               "Segment",
        "annual_commit_dollars": "Annual Commit$$",
        "days_to_renewal":       "Days to Renewal",
        "avr_score":             "AVR Score",
        "band":                  "AVR Health",
    })
    st.dataframe(exp_display, width="stretch", hide_index=True, height=380)

st.divider()

# --------------------------------------------------------------------------
# Section 6 — Account Details (all accounts in current filter)
# --------------------------------------------------------------------------
# Added 2026-07-06 to answer the natural exec / interview question "the KPIs
# say N accounts — which N?" The Expansion Opportunities table above only
# shows expansion-flagged rows (a subset). This section shows the full N.
# Same table style as Section 5 for visual consistency; extra column
# `Days in Contract` surfaces ramp status per row.
st.subheader("Account Details")
st.caption(
    "All accounts matching the sidebar filters on this snapshot. "
    "Ranked by ARR (largest first). Click any column header to re-sort — "
    "e.g. click **AVR Score** ascending to see the highest-risk accounts first, "
    "or a component (**D / C / B / R / T**) ascending to find accounts where "
    "that specific driver is weakest. All 6 score columns are on the same 0–100 "
    "scale as the KPI cards. Top 500."
)

all_accts = load_all_filtered_accounts(
    selected_snapshot,
    tuple(selected_regions),
    tuple(selected_csms),
    tuple(selected_segments),
    tuple(selected_accounts),
    include_ramped=include_ramped,
    include_ramping=include_ramping,
)

if all_accts.empty:
    st.info("No accounts match the current filter set.")
else:
    all_display = all_accts.copy()
    all_display["annual_commit_dollars"] = all_display["annual_commit_dollars"].apply(fmt_currency)
    # Hide raw IDs; execs only need company_name to identify the customer.
    all_display = all_display.drop(columns=["account_id", "csm_id"], errors="ignore")
    # Reorder for exec scanability: identity → ARR → 5 component drivers
    # (D/C/B/R/T) → composite AVR Score → health band → contract tenure.
    # Score sits adjacent to Health so the composite→band mapping reads at a
    # glance (a 42 next to Red, an 81 next to Green). Component order D/C/B/R/T
    # is a deliberate ask — consumption-side drivers (D/C/B) adjacent for
    # at-a-glance comparison, then service-side (R/T).
    all_display = all_display[[
        "company_name", "region", "segment", "annual_commit_dollars",
        "d_score", "c_score", "b_score", "r_score", "t_score",
        "avr_score", "band",
        "days_in_contract", "days_to_renewal",
    ]]
    all_display = all_display.rename(columns={
        "company_name":          "Customer",
        "region":                "Region",
        "segment":               "Segment",
        "annual_commit_dollars": "Annual Commit$$",
        "avr_score":             "AVR Score",
        "d_score":               "D",
        "c_score":               "C",
        "b_score":               "B",
        "r_score":               "R",
        "t_score":               "T",
        "band":                  "AVR Health",
        "days_in_contract":      "Days in Contract",
        "days_to_renewal":       "Days to Renewal",
    })
    st.dataframe(all_display, width="stretch", hide_index=True, height=380)
    st.caption(
        f"Showing **{len(all_accts):,}** of the account count in the top KPI card "
        "(same filter set, same snapshot). Ramping accounts have blank AVR Score "
        "and `AVR Health = Onboarding` by design — see `specs/01 § Known limitations`. "
        "Component scores (D/C/B/R/T) stay populated even during ramp so the driver "
        "profile is visible for audit."
    )

st.divider()

# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------
st.divider()
st.caption(
    "GCS-NorthStar · Phase 3 · spec `specs/08-dashboard.md` · "
    "data refreshed by `make dbt-build` · "
    f"BigQuery project `{PROJECT_ID}`."
)
