"""Generate the daily_usage_logs table (base pass — before anomaly injection).

Spec references: 02-data-model.md#daily_usage_logs, 03-generation-rules.md#daily-usage-logs.
Each active contract generates roughly `DAILY_USAGE_PROB * contract_days` rows.
Anomaly injection (spike/drop, shelfware, overages, orphans, out-of-window) is
done in anomalies.py.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import List

import numpy as np
import pandas as pd

from data_generation import config


def generate(contracts: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(config.SEED + 3)
    np_rng = np.random.default_rng(config.SEED + 3)

    # Cap generation at the run window's end so we never produce future data
    window_end = config.WINDOW_END

    rows: List[dict] = []
    for _, c in contracts.iterrows():
        start = c["start_date"]
        # Only generate up to today or contract end, whichever is earlier
        end = min(c["end_date"], window_end)
        if end < start:
            continue

        daily_target = c["included_monthly_compute_credits"] / 30.0
        n_days = (end - start).days + 1

        # Bernoulli mask for "active" days
        active = np_rng.random(n_days) < config.DAILY_USAGE_PROB
        # Lognormal multipliers around the daily target
        multipliers = np_rng.lognormal(mean=0.0, sigma=config.DAILY_USAGE_LN_SIGMA, size=n_days)

        for i in range(n_days):
            if not active[i]:
                continue
            d = start + timedelta(days=i)
            credits = int(round(daily_target * multipliers[i] / 100.0) * 100)
            if credits <= 0:
                continue
            rows.append({
                "account_id": c["account_id"],
                "date": d,
                "compute_credits_consumed": credits,
                # log_id assigned later so numbering is contiguous after
                # anomalies inject/delete rows
            })

    df = pd.DataFrame(rows)
    return df


def finalize_log_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Assign contiguous log_id values AFTER anomaly injection."""
    df = df.reset_index(drop=True).copy()
    df.insert(0, "log_id", [f"LOG-{i:07d}" for i in range(1, len(df) + 1)])
    return df
