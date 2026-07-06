"""Generate the contracts table (base pass — before anomaly injection).

Spec references: 02-data-model.md#contracts, 03-generation-rules.md#contracts.
Renewals are added here (contract_type='Renewal'); Expansions are injected in
anomalies.py (edge case #4) so the mid-year overlap count is deterministic.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from data_generation import config


def _loguniform(rng: random.Random, low: float, high: float) -> float:
    return math.exp(rng.uniform(math.log(low), math.log(high)))


def _round_to_month(d: date) -> date:
    """Round to the first day of the month for cleaner reporting cadence."""
    return date(d.year, d.month, 1)


def _annual_commit(rng: random.Random, segment: str) -> int:
    low, high = (
        config.COMMIT_ENTERPRISE if segment == "Enterprise" else config.COMMIT_MIDMARKET
    )
    return int(round(_loguniform(rng, low, high) / 1000.0) * 1000)


def _monthly_credits(annual_commit_dollars: int) -> int:
    return int(round(annual_commit_dollars / 12.0 / config.PRICE_PER_CREDIT))


def generate(accounts: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(config.SEED + 2)

    contract_rows: List[dict] = []
    ctr_counter = 0

    def next_id() -> str:
        nonlocal ctr_counter
        ctr_counter += 1
        return f"CTR-{ctr_counter:06d}"

    # --- Base pass: one contract per account ---
    for _, acct in accounts.iterrows():
        segment = acct["segment"]
        signup = acct["signup_date"]
        # Contract starts at max(signup_date, WINDOW_START), rounded to month
        earliest = max(signup, config.WINDOW_START)
        start = _round_to_month(earliest + timedelta(days=rng.randint(0, 60)))
        if start < config.WINDOW_START:
            start = config.WINDOW_START
        end = start + timedelta(days=365)
        commit = _annual_commit(rng, segment)
        contract_rows.append({
            "contract_id": next_id(),
            "account_id": acct["account_id"],
            "start_date": start,
            "end_date": end,
            "annual_commit_dollars": commit,
            "included_monthly_compute_credits": _monthly_credits(commit),
            "contract_type": "New",
        })

    # --- Renewal pass: ~200 accounts get a second contract ---
    account_ids = accounts["account_id"].tolist()
    renewal_accts = rng.sample(account_ids, config.N_RENEWALS)

    # Build lookup for base contract by account
    base_by_acct = {row["account_id"]: row for row in contract_rows}

    # Clip so every contract has at least 30 days of observable usage in window
    max_start = config.WINDOW_END - timedelta(days=30)

    for aid in renewal_accts:
        base = base_by_acct[aid]
        renewal_start = base["end_date"] + timedelta(days=rng.randint(-15, 30))
        if renewal_start > max_start:
            renewal_start = max_start
        renewal_end = renewal_start + timedelta(days=365)
        # Renewals typically same or slightly higher commit
        commit_multiplier = rng.uniform(0.95, 1.30)
        commit = int(round(base["annual_commit_dollars"] * commit_multiplier / 1000.0) * 1000)
        contract_rows.append({
            "contract_id": next_id(),
            "account_id": aid,
            "start_date": renewal_start,
            "end_date": renewal_end,
            "annual_commit_dollars": commit,
            "included_monthly_compute_credits": _monthly_credits(commit),
            "contract_type": "Renewal",
        })

    return pd.DataFrame(contract_rows)
