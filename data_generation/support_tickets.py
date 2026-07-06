"""Generate the support_tickets table.

Spec references: 02-data-model.md#support_tickets, 03-generation-rules.md#support-tickets.
Ticket count per account-month follows Poisson(lambda_segment).
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List

import numpy as np
import pandas as pd

from data_generation import config


def _weighted_choice(rng: random.Random, weights: dict) -> str:
    keys = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(keys, weights=probs, k=1)[0]


def _months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def generate(accounts: pd.DataFrame, contracts: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(config.SEED + 4)
    np_rng = np.random.default_rng(config.SEED + 4)

    # Merge segment onto contracts
    contracts_seg = contracts.merge(
        accounts[["account_id", "segment"]], on="account_id", how="left"
    )

    # Cap ticket window to run window
    window_end = config.WINDOW_END

    rows: List[dict] = []
    tck_counter = 0

    for _, c in contracts_seg.iterrows():
        start = c["start_date"]
        end = min(c["end_date"], window_end)
        if end < start:
            continue

        lam = (
            config.TICKET_LAMBDA_ENTERPRISE
            if c["segment"] == "Enterprise"
            else config.TICKET_LAMBDA_MIDMARKET
        )
        n_months = _months_between(start, end)
        n_tickets = int(np_rng.poisson(lam * n_months))
        span_days = (end - start).days

        for _ in range(n_tickets):
            offset = rng.randint(0, max(0, span_days))
            opened = start + timedelta(days=offset)
            severity = _weighted_choice(rng, config.SEVERITY_WEIGHTS)
            product_area = _weighted_choice(rng, config.PRODUCT_AREA_WEIGHTS)
            status = _weighted_choice(rng, config.STATUS_WEIGHTS)

            resolution_days = float(np_rng.exponential(config.RESOLUTION_DAYS_MEAN[severity]))
            if status == "Open":
                closed = None
            elif status == "In Progress":
                # In-progress tickets have no closed_date but may be old
                closed = None
            else:
                closed = opened + timedelta(days=max(0, int(round(resolution_days))))
                # Never close past window end
                if closed > window_end:
                    closed = window_end

            tck_counter += 1
            rows.append({
                "ticket_id": f"TCK-{tck_counter:06d}",
                "account_id": c["account_id"],
                "opened_date": opened,
                "closed_date": closed,
                "severity": severity,
                "product_area": product_area,
                "status": status,
            })

    return pd.DataFrame(rows)
