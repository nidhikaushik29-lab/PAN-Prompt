"""Inject the 5 mandated anomalies into contracts + daily_usage_logs.

Spec references: 04-edge-cases.md.

Anomaly ordering matters. We select disjoint account samples via a shrinking
pool so no account is both spike-drop and shelfware, etc.

All modifications happen on `usage_df` (a DataFrame of daily log rows without
log_id yet) and `contracts_df`. Final log_id assignment happens in
usage.finalize_log_ids AFTER this pass.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from typing import List, Tuple

import numpy as np
import pandas as pd

from data_generation import config


def _round100(x: float) -> int:
    return int(round(x / 100.0) * 100)


def _daily_lognormal(np_rng: np.random.Generator, mean_target: float, n: int) -> np.ndarray:
    mults = np_rng.lognormal(mean=0.0, sigma=config.DAILY_USAGE_LN_SIGMA, size=n)
    return np.maximum(0, mean_target * mults)


def inject(
    accounts: pd.DataFrame,
    contracts: pd.DataFrame,
    usage: pd.DataFrame,
    tickets: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Return (contracts, usage, tickets, injection_report_dict) all modified."""

    rng = random.Random(config.SEED + 5)
    np_rng = np.random.default_rng(config.SEED + 5)

    all_account_ids = accounts["account_id"].tolist()
    remaining = set(all_account_ids)

    # Contract lookup for first contract of each account (base contract by start_date)
    base_by_acct = (
        contracts.sort_values("start_date")
        .drop_duplicates("account_id", keep="first")
        .set_index("account_id")
        .to_dict("index")
    )

    injection_report = {}

    # -----------------------------------------------------------------------
    # #1 — Spike & Drop
    # -----------------------------------------------------------------------
    spike_accts = set(rng.sample(sorted(remaining), config.N_SPIKE_DROP))
    remaining -= spike_accts

    # Remove existing usage for these accounts
    usage = usage[~usage["account_id"].isin(spike_accts)].copy()

    new_rows: List[dict] = []
    for aid in spike_accts:
        base = base_by_acct[aid]
        start = base["start_date"]
        end = min(base["end_date"], config.WINDOW_END)
        annual_budget = base["included_monthly_compute_credits"] * 12

        # Month 1 window: first 30 days from start, clipped to window
        m1_end = min(start + timedelta(days=29), end)
        m1_days = (m1_end - start).days + 1
        # Total month-1 sum should be ~90% of annual budget
        m1_total = int(round(annual_budget * 0.90))
        # Distribute across ~25-30 days with lognormal noise
        if m1_days > 0:
            weights = np_rng.random(m1_days) ** 2 + 0.2   # skew toward larger values
            weights /= weights.sum()
            per_day = np.round(weights * m1_total / 100.0) * 100
            for i in range(m1_days):
                v = int(per_day[i])
                if v > 0:
                    new_rows.append({
                        "account_id": aid,
                        "date": start + timedelta(days=i),
                        "compute_credits_consumed": v,
                    })

        # Months 2..end: very sparse light usage (~2% of daily target on 10% of days)
        after_m1_start = start + timedelta(days=30)
        if after_m1_start <= end:
            n_days = (end - after_m1_start).days + 1
            daily_target = base["included_monthly_compute_credits"] / 30.0
            active = np_rng.random(n_days) < 0.10
            for i in range(n_days):
                if active[i]:
                    v = _round100(daily_target * 0.02 * np_rng.uniform(0.5, 1.5))
                    if v > 0:
                        new_rows.append({
                            "account_id": aid,
                            "date": after_m1_start + timedelta(days=i),
                            "compute_credits_consumed": v,
                        })

    if new_rows:
        usage = pd.concat([usage, pd.DataFrame(new_rows)], ignore_index=True)

    injection_report["spike_drop_accounts"] = len(spike_accts)

    # -----------------------------------------------------------------------
    # #2 — Shelfware
    # -----------------------------------------------------------------------
    shelf_accts = set(rng.sample(sorted(remaining), config.N_SHELFWARE))
    remaining -= shelf_accts

    # Remove ALL usage for shelfware accounts
    usage = usage[~usage["account_id"].isin(shelf_accts)].copy()

    # Bump their commit to the top of their segment
    acct_seg = accounts.set_index("account_id")["segment"].to_dict()
    for aid in shelf_accts:
        seg = acct_seg[aid]
        # Push toward upper half of segment range
        if seg == "Enterprise":
            new_commit = int(rng.uniform(800_000, 2_000_000) / 1000) * 1000
        else:
            new_commit = int(rng.uniform(100_000, 200_000) / 1000) * 1000
        mask = contracts["account_id"] == aid
        contracts.loc[mask, "annual_commit_dollars"] = new_commit
        contracts.loc[mask, "included_monthly_compute_credits"] = int(
            round(new_commit / 12.0 / config.PRICE_PER_CREDIT)
        )

    # Reduce their ticket volume by 70% (customers not using don't file tickets)
    shelf_ticket_mask = tickets["account_id"].isin(shelf_accts)
    shelf_tickets = tickets[shelf_ticket_mask]
    keep_frac = 0.30
    n_keep = int(len(shelf_tickets) * keep_frac)
    if n_keep < len(shelf_tickets):
        # Random subset to keep
        keep_idx = shelf_tickets.sample(n=n_keep, random_state=config.SEED + 5).index
        drop_idx = shelf_tickets.index.difference(keep_idx)
        tickets = tickets.drop(drop_idx).copy()

    injection_report["shelfware_accounts"] = len(shelf_accts)

    # -----------------------------------------------------------------------
    # #3 — Consistent Overages
    # -----------------------------------------------------------------------
    over_accts = set(rng.sample(sorted(remaining), config.N_OVERAGE))
    remaining -= over_accts

    # Wipe base usage for these accounts and regenerate with monthly overage
    usage = usage[~usage["account_id"].isin(over_accts)].copy()

    new_rows = []
    for aid in over_accts:
        base = base_by_acct[aid]
        start = base["start_date"]
        end = min(base["end_date"], config.WINDOW_END)
        monthly_allot = base["included_monthly_compute_credits"]

        # Iterate month-by-month
        cur = start
        while cur <= end:
            # Month-end (30 days or contract end, whichever is earlier)
            m_end = min(cur + timedelta(days=29), end)
            m_days = (m_end - cur).days + 1
            multiplier = rng.uniform(1.20, 1.60)
            month_total = int(round(monthly_allot * multiplier))
            # Distribute across days
            weights = np_rng.random(m_days) + 0.5
            weights /= weights.sum()
            per_day = np.round(weights * month_total / 100.0) * 100
            for i in range(m_days):
                v = int(per_day[i])
                if v > 0:
                    new_rows.append({
                        "account_id": aid,
                        "date": cur + timedelta(days=i),
                        "compute_credits_consumed": v,
                    })
            cur = m_end + timedelta(days=1)

    if new_rows:
        usage = pd.concat([usage, pd.DataFrame(new_rows)], ignore_index=True)

    injection_report["overage_accounts"] = len(over_accts)

    # -----------------------------------------------------------------------
    # #4 — Mid-Year Expansions
    # -----------------------------------------------------------------------
    exp_accts = set(rng.sample(sorted(remaining), config.N_EXPANSIONS))
    remaining -= exp_accts

    # Determine next contract_id number
    max_ctr = (
        contracts["contract_id"]
        .str.replace("CTR-", "", regex=False)
        .astype(int)
        .max()
    )
    next_num = max_ctr + 1

    expansion_rows = []
    max_start = config.WINDOW_END - timedelta(days=30)  # keep ≥30 observable days
    for aid in exp_accts:
        base = base_by_acct[aid]
        offset_days = rng.randint(120, 270)
        exp_start = base["start_date"] + timedelta(days=offset_days)
        if exp_start > max_start:
            exp_start = max_start
        exp_end = base["end_date"] + timedelta(days=rng.randint(180, 365))
        exp_commit = int(base["annual_commit_dollars"] * rng.uniform(1.5, 3.0) / 1000) * 1000
        exp_monthly_credits = int(round(exp_commit / 12.0 / config.PRICE_PER_CREDIT))
        expansion_rows.append({
            "contract_id": f"CTR-{next_num:06d}",
            "account_id": aid,
            "start_date": exp_start,
            "end_date": exp_end,
            "annual_commit_dollars": exp_commit,
            "included_monthly_compute_credits": exp_monthly_credits,
            "contract_type": "Expansion",
        })
        next_num += 1

        # Bump usage after expansion start to ~80% of new (larger) allotment
        # Delete existing usage after exp_start, regenerate at higher level
        mask = (usage["account_id"] == aid) & (usage["date"] >= exp_start)
        usage = usage[~mask].copy()

        cur = exp_start
        end_cap = min(exp_end, config.WINDOW_END)
        daily_target = exp_monthly_credits / 30.0 * 0.80
        n_days = (end_cap - cur).days + 1
        if n_days > 0:
            active = np_rng.random(n_days) < config.DAILY_USAGE_PROB
            mults = np_rng.lognormal(mean=0.0, sigma=config.DAILY_USAGE_LN_SIGMA, size=n_days)
            for i in range(n_days):
                if active[i]:
                    v = _round100(daily_target * mults[i])
                    if v > 0:
                        usage = pd.concat(
                            [usage, pd.DataFrame([{
                                "account_id": aid,
                                "date": cur + timedelta(days=i),
                                "compute_credits_consumed": v,
                            }])],
                            ignore_index=True,
                        )

    if expansion_rows:
        contracts = pd.concat([contracts, pd.DataFrame(expansion_rows)], ignore_index=True)

    injection_report["expansion_accounts"] = len(exp_accts)

    # -----------------------------------------------------------------------
    # #6 — Approaching Cap (steady consumers in [0.90, 1.20) × allotment)
    # -----------------------------------------------------------------------
    # Purpose: seed the Section-5 expansion pipeline with a visible population
    # of accounts sitting just under the 120% overage bar but at/above the
    # 0.90 × allotment expansion threshold. Distinct from #3 Overages —
    # multiplier strictly < 1.20 so EC-3 signal remains clean.
    # Inserted at end of injection sequence to preserve determinism of
    # cohorts #1-#4.
    approach_accts = set(rng.sample(sorted(remaining), config.N_APPROACHING_CAP))
    remaining -= approach_accts

    # Wipe normal-pass usage for these accounts and regenerate steady band
    usage = usage[~usage["account_id"].isin(approach_accts)].copy()

    # Iterate CONTRACT-by-CONTRACT so accounts with renewals produce usage
    # spanning the full contract chain (base + renewal), each at its own
    # allotment. Overlapping (renewal starts before base ends) is resolved
    # by clipping the earlier contract's end to (next.start - 1) so no
    # double-counting occurs.
    contracts_by_acct = {
        aid: g.sort_values("start_date").reset_index(drop=True)
        for aid, g in contracts[contracts["account_id"].isin(approach_accts)].groupby("account_id")
    }

    new_rows = []
    for aid in approach_accts:
        acct_ctrs = contracts_by_acct[aid]
        for idx, ctr in acct_ctrs.iterrows():
            start = ctr["start_date"]
            end = min(ctr["end_date"], config.WINDOW_END)
            # If a later contract starts before this one ends, cap end
            if idx + 1 < len(acct_ctrs):
                next_start = acct_ctrs.loc[idx + 1, "start_date"]
                if next_start <= end:
                    end = next_start - timedelta(days=1)
            if end < start:
                continue
            monthly_allot = ctr["included_monthly_compute_credits"]

            # Iterate 30-day generator-months (same cadence as overage cohort)
            cur = start
            while cur <= end:
                m_end = min(cur + timedelta(days=29), end)
                m_days = (m_end - cur).days + 1
                # rng.random() ∈ [0, 1) → multiplier strictly in [0.90, 1.20)
                multiplier = 0.90 + rng.random() * 0.30
                month_total = int(round(monthly_allot * multiplier))
                weights = np_rng.random(m_days) + 0.5
                weights /= weights.sum()
                per_day = np.round(weights * month_total / 100.0) * 100
                for i in range(m_days):
                    v = int(per_day[i])
                    if v > 0:
                        new_rows.append({
                            "account_id": aid,
                            "date": cur + timedelta(days=i),
                            "compute_credits_consumed": v,
                        })
                cur = m_end + timedelta(days=1)

    if new_rows:
        usage = pd.concat([usage, pd.DataFrame(new_rows)], ignore_index=True)

    injection_report["approaching_cap_accounts"] = len(approach_accts)

    # -----------------------------------------------------------------------
    # #5 — Orphaned + Out-of-Window Usage
    # -----------------------------------------------------------------------
    # 5a: orphan logs with fake account_ids
    orphan_rows = []
    window_days = (config.WINDOW_END - config.WINDOW_START).days
    for _ in range(config.N_ORPHAN_LOGS):
        orphan_rows.append({
            "account_id": f"UUID-{uuid.UUID(int=rng.getrandbits(128)).hex[:8]}",
            "date": config.WINDOW_START + timedelta(days=rng.randint(0, window_days)),
            "compute_credits_consumed": _round100(rng.uniform(500, 20_000)),
        })

    # 5b: out-of-window logs (real account, date outside any contract)
    # EXCLUDE shelfware accounts — they must remain zero-usage for EC-2.
    oow_rows = []
    real_accounts = [a for a in accounts["account_id"].tolist() if a not in shelf_accts]
    contract_span_by_acct = (
        contracts.groupby("account_id")
        .agg(min_start=("start_date", "min"), max_end=("end_date", "max"))
        .to_dict("index")
    )
    picks = rng.sample(real_accounts, config.N_OUT_OF_WINDOW_LOGS)
    for i, aid in enumerate(picks):
        span = contract_span_by_acct[aid]
        min_start = span["min_start"]
        max_end = span["max_end"]
        # Half before, half after
        if i < config.N_OUT_OF_WINDOW_LOGS // 2:
            # Before: 1-90 days before min_start
            days_before = rng.randint(1, 90)
            d = min_start - timedelta(days=days_before)
        else:
            # After: 1-90 days after max_end (but still clipped to window+90)
            days_after = rng.randint(1, 90)
            d = max_end + timedelta(days=days_after)
        oow_rows.append({
            "account_id": aid,
            "date": d,
            "compute_credits_consumed": _round100(rng.uniform(500, 10_000)),
        })

    if orphan_rows or oow_rows:
        usage = pd.concat(
            [usage, pd.DataFrame(orphan_rows), pd.DataFrame(oow_rows)],
            ignore_index=True,
        )

    injection_report["orphan_logs"] = len(orphan_rows)
    injection_report["out_of_window_logs"] = len(oow_rows)

    # Sort usage by (account_id, date) for stable output
    usage = usage.sort_values(["account_id", "date"]).reset_index(drop=True)

    return contracts, usage, tickets, injection_report
