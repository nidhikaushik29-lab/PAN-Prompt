"""Central configuration for the synthetic-data generator.

Every generator module imports from here so tuning knobs live in one place.
Changing SEED and re-running `make generate` will still be deterministic.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
SEED = 42

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "raw"

# ---------------------------------------------------------------------------
# Time window (per spec 03)
# ---------------------------------------------------------------------------
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 6, 30)

# ---------------------------------------------------------------------------
# Volume targets (per spec 03)
# ---------------------------------------------------------------------------
N_CSM_REPS = 50
N_ACCOUNTS = 1_000
N_BASE_CONTRACTS = 1_000                # one per account, +renewals via anomalies/expansions
N_RENEWALS = 170                        # ~200 total additional contracts (renewals + expansions)
TARGET_TICKETS_TOTAL = 30_000           # soft target; Poisson draws control actual
TARGET_USAGE_ROWS = 200_000             # before orphan additions

# ---------------------------------------------------------------------------
# Segment / demographic distributions
# ---------------------------------------------------------------------------
ENTERPRISE_FRAC = 0.40
REGION_WEIGHTS = {"AMER": 0.45, "EMEA": 0.30, "APAC": 0.15, "JAPAC": 0.10}
INDUSTRY_WEIGHTS = {
    "Financial Services": 0.20,
    "Technology": 0.20,
    "Healthcare": 0.15,
    "Retail": 0.15,
    "Manufacturing": 0.15,
    "Media": 0.10,
    "Public Sector": 0.05,
}

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
PRICE_PER_CREDIT = 0.05   # dollars per compute credit

# ---------------------------------------------------------------------------
# Contract commit ranges (dollars per year)
# ---------------------------------------------------------------------------
COMMIT_ENTERPRISE = (200_000, 2_000_000)
COMMIT_MIDMARKET = (25_000, 200_000)

# ---------------------------------------------------------------------------
# Support ticket parameters
# ---------------------------------------------------------------------------
TICKET_LAMBDA_ENTERPRISE = 3.5   # per active month per account
TICKET_LAMBDA_MIDMARKET = 1.2
SEVERITY_WEIGHTS = {1: 0.03, 2: 0.12, 3: 0.85}  # integer severity: 1=critical, 2=high, 3=low (P3+P4 collapsed)
PRODUCT_AREA_WEIGHTS = {
    "Compute": 0.30,
    "Storage": 0.15,
    "Networking": 0.10,
    "Auth": 0.10,
    "API": 0.20,
    "UI": 0.10,
    "Billing": 0.05,
}
STATUS_WEIGHTS = {"Open": 0.05, "In Progress": 0.10, "Resolved": 0.15, "Closed": 0.70}
RESOLUTION_DAYS_MEAN = {1: 1.0, 2: 3.0, 3: 15.0}  # sev3 = weighted avg of old P3(10d)+P4(21d)

# ---------------------------------------------------------------------------
# Usage parameters
# ---------------------------------------------------------------------------
DAILY_USAGE_PROB = 0.55         # probability an account has usage on a given day
DAILY_USAGE_LN_SIGMA = 0.35     # lognormal spread around mean daily target

# ---------------------------------------------------------------------------
# Edge-case injection targets (per spec 04)
# ---------------------------------------------------------------------------
N_SPIKE_DROP = 50
N_SHELFWARE = 100
N_OVERAGE = 150
N_EXPANSIONS = 30
N_APPROACHING_CAP = 100          # steady consumers in [0.90, 1.20) × allotment
N_ORPHAN_LOGS = 200
N_OUT_OF_WINDOW_LOGS = 100
