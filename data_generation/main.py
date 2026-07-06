"""Orchestrator: generate all 6 tables and write to data/raw/*.csv.

Run via `make generate` (equivalent: `python -m data_generation.main`).

Pipeline order (per spec 03):
  1. csm_reps
  2. accounts
  3. contracts (base + renewals)
  4. usage      (base pass, no log_ids yet)
  5. tickets
  6. anomalies  (mutates contracts, usage, tickets)
  7. finalize log_ids on usage
  8. health     (weekly rollup — runs LAST so it sees anomaly state)
"""
from __future__ import annotations

import time

import pandas as pd

from data_generation import (
    accounts,
    anomalies,
    config,
    contracts,
    csm_reps,
    health,
    support_tickets,
    usage,
)


def _write(df: pd.DataFrame, name: str) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DATA_DIR / f"{name}.csv"
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"  wrote {path.relative_to(config.ROOT)}  rows={len(df):,}")


def main() -> None:
    t0 = time.time()
    print(f"GCS North Star data generation — seed={config.SEED}")
    print(f"Output directory: {config.DATA_DIR}")
    print()

    print("1/7 csm_reps ...")
    csm_df = csm_reps.generate()

    print("2/7 accounts ...")
    acct_df = accounts.generate(csm_df)

    print("3/7 contracts (base + renewals) ...")
    ctr_df = contracts.generate(acct_df)

    print("4/7 daily_usage_logs (base pass) ...")
    usage_df = usage.generate(ctr_df)
    print(f"    base usage rows: {len(usage_df):,}")

    print("5/7 support_tickets ...")
    tkt_df = support_tickets.generate(acct_df, ctr_df)
    print(f"    base ticket rows: {len(tkt_df):,}")

    print("6/7 anomaly injection (6 edge cases) ...")
    ctr_df, usage_df, tkt_df, report = anomalies.inject(acct_df, ctr_df, usage_df, tkt_df)
    for k, v in report.items():
        print(f"    {k}: {v}")

    # Finalize contiguous log_ids after all anomaly additions/deletions
    usage_df = usage.finalize_log_ids(usage_df)

    print("7/7 account_health (weekly rollup) ...")
    health_df = health.generate(acct_df, ctr_df, usage_df, tkt_df)

    # -----------------------------------------------------------------------
    # Write out CSVs
    # -----------------------------------------------------------------------
    print("\nWriting CSVs ...")
    _write(csm_df, "csm_reps")
    _write(acct_df, "accounts")
    _write(ctr_df, "contracts")
    _write(tkt_df, "support_tickets")
    _write(health_df, "account_health")
    _write(usage_df, "daily_usage_logs")

    dt = time.time() - t0
    print(f"\nDone in {dt:.1f}s.")


if __name__ == "__main__":
    main()
