"""Generate the csm_reps table.

Spec references: 02-data-model.md#csm_reps, 03-generation-rules.md#csm-reps.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List

import pandas as pd
from faker import Faker

from data_generation import config


def _weighted_choice(rng: random.Random, weights: dict) -> str:
    """random.choices with an explicit RNG (for determinism)."""
    keys = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(keys, weights=probs, k=1)[0]


def generate() -> pd.DataFrame:
    rng = random.Random(config.SEED)
    fake = Faker()
    Faker.seed(config.SEED)

    n_enterprise = int(round(config.N_CSM_REPS * config.ENTERPRISE_FRAC))
    segments = ["Enterprise"] * n_enterprise + ["Mid-Market"] * (
        config.N_CSM_REPS - n_enterprise
    )
    rng.shuffle(segments)

    hire_min = date(2020, 1, 1)
    hire_max = date(2024, 12, 31)
    span_days = (hire_max - hire_min).days

    rows: List[dict] = []
    for i in range(1, config.N_CSM_REPS + 1):
        rows.append({
            "csm_id": f"CSM-{i:04d}",
            "name": fake.name(),
            "region": _weighted_choice(rng, config.REGION_WEIGHTS),
            "segment": segments[i - 1],
            "hire_date": hire_min + timedelta(days=rng.randint(0, span_days)),
        })

    df = pd.DataFrame(rows)
    return df
