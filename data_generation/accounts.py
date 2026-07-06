"""Generate the accounts table.

Spec references: 02-data-model.md#accounts, 03-generation-rules.md#accounts.
Segment ratio and CSM assignment: 40% Enterprise / 60% Mid-Market; each
account is assigned to a CSM whose segment matches (SEG-1 in spec 05).

FK naming: this table stores the assigned CSM under `rep_id` — the value is
still a `csm_reps.csm_id`, but we preserve the business-side name `rep_id`.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List

import pandas as pd
from faker import Faker

from data_generation import config


def _weighted_choice(rng: random.Random, weights: dict) -> str:
    keys = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(keys, weights=probs, k=1)[0]


def generate(csm_reps: pd.DataFrame) -> pd.DataFrame:
    # Distinct RNG offset so account randomness is uncorrelated with CSM ordering
    rng = random.Random(config.SEED + 1)
    fake = Faker()
    Faker.seed(config.SEED + 1)

    n_enterprise = int(round(config.N_ACCOUNTS * config.ENTERPRISE_FRAC))
    segments = ["Enterprise"] * n_enterprise + ["Mid-Market"] * (
        config.N_ACCOUNTS - n_enterprise
    )
    rng.shuffle(segments)

    # Pre-split CSMs by segment so we can assign in O(1)
    csms_by_segment = {
        "Enterprise": csm_reps.loc[csm_reps["segment"] == "Enterprise", "csm_id"].tolist(),
        "Mid-Market": csm_reps.loc[csm_reps["segment"] == "Mid-Market", "csm_id"].tolist(),
    }

    signup_min = date(2022, 1, 1)
    signup_max = date(2025, 6, 1)
    span = (signup_max - signup_min).days

    rows: List[dict] = []
    for i in range(1, config.N_ACCOUNTS + 1):
        segment = segments[i - 1]
        rows.append({
            "account_id": f"ACCT-{i:06d}",
            "company_name": fake.company(),
            "industry": _weighted_choice(rng, config.INDUSTRY_WEIGHTS),
            "rep_id": rng.choice(csms_by_segment[segment]),
            "segment": segment,
            "signup_date": signup_min + timedelta(days=rng.randint(0, span)),
        })
    return pd.DataFrame(rows)
