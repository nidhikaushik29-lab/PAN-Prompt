"""Generate the account_health weekly snapshot table.

Spec references: 02-data-model.md#account_health, 03-generation-rules.md.

Grain: one row per account per week ending Sunday, only for weeks where the
account has an active contract. health_color is derived from weekly usage
fraction of monthly allotment AND open severity-1/2 ticket volume.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List

import pandas as pd

from data_generation import config


def _sundays_in_range(start: date, end: date):
    """Yield the Sunday date at the end of each week in [start, end]."""
    # Move to first Sunday on or after start
    days_to_sunday = (6 - start.weekday()) % 7   # weekday(): Monday=0..Sunday=6
    d = start + timedelta(days=days_to_sunday)
    while d <= end:
        yield d
        d += timedelta(days=7)


def generate(
    accounts: pd.DataFrame,
    contracts: pd.DataFrame,
    usage: pd.DataFrame,
    tickets: pd.DataFrame,
) -> pd.DataFrame:
    # Cast dates to pandas Timestamps for vectorized ops
    usage_df = usage.copy()
    usage_df["date"] = pd.to_datetime(usage_df["date"])
    tickets_df = tickets.copy()
    tickets_df["opened_date"] = pd.to_datetime(tickets_df["opened_date"])
    tickets_df["closed_date"] = pd.to_datetime(tickets_df["closed_date"])
    contracts_df = contracts.copy()
    contracts_df["start_date"] = pd.to_datetime(contracts_df["start_date"])
    contracts_df["end_date"] = pd.to_datetime(contracts_df["end_date"])

    # Compute per-account contract span (min start, max end)
    span = contracts_df.groupby("account_id").agg(
        min_start=("start_date", "min"),
        max_end=("end_date", "max"),
    )

    rows: List[dict] = []
    for aid in accounts["account_id"]:
        if aid not in span.index:
            continue
        start = span.loc[aid, "min_start"].date()
        end = min(span.loc[aid, "max_end"].date(), config.WINDOW_END)
        if end < start:
            continue

        acct_usage = usage_df[usage_df["account_id"] == aid]
        acct_tickets = tickets_df[tickets_df["account_id"] == aid]
        acct_contracts = contracts_df[contracts_df["account_id"] == aid]

        for sunday in _sundays_in_range(start, end):
            week_start = sunday - timedelta(days=6)
            # Weekly usage sum
            wu = acct_usage[
                (acct_usage["date"] >= pd.Timestamp(week_start))
                & (acct_usage["date"] <= pd.Timestamp(sunday))
            ]["compute_credits_consumed"].sum()

            # Find the applicable contract for this Sunday
            applicable = acct_contracts[
                (acct_contracts["start_date"] <= pd.Timestamp(sunday))
                & (acct_contracts["end_date"] >= pd.Timestamp(sunday))
            ]
            if applicable.empty:
                continue
            # If multiple (expansion overlap), use the newest start
            applicable = applicable.sort_values("start_date").iloc[-1]
            monthly_allot = applicable["included_monthly_compute_credits"]
            # Weekly allotment ~= monthly / 4.33
            weekly_allot = monthly_allot / 4.33
            frac = wu / weekly_allot if weekly_allot > 0 else 0

            # Open severity-1 and severity-2 tickets as of this Sunday
            open_sev1or2 = acct_tickets[
                (acct_tickets["severity"].isin([1, 2]))
                & (acct_tickets["opened_date"] <= pd.Timestamp(sunday))
                & (
                    acct_tickets["closed_date"].isna()
                    | (acct_tickets["closed_date"] > pd.Timestamp(sunday))
                )
            ]
            n_open_sev1or2 = len(open_sev1or2)
            n_open_sev1_over_7d = len(
                open_sev1or2[
                    (open_sev1or2["severity"] == 1)
                    & (open_sev1or2["opened_date"] < pd.Timestamp(sunday) - pd.Timedelta(days=7))
                ]
            )

            # Health color rule
            if frac < 0.05 or n_open_sev1or2 > 5 or n_open_sev1_over_7d > 0:
                color = "Red"
            elif frac < 0.15 or n_open_sev1or2 >= 3:
                color = "Yellow"
            else:
                color = "Green"

            rows.append({
                "account_id": aid,
                "date": sunday,
                "health_color": color,
                "compute_credits_consumed": int(wu),
            })

    return pd.DataFrame(rows)
