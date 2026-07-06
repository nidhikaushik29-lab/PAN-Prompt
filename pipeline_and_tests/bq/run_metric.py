"""Execute north_star_metric.sql and print the top-N Red and Expansion lists.

Also writes data/metric_smoke.md summarizing the AVR distribution.
Spec references: 05-data-quality-tests.md MET-1/2/3, 06-bigquery-deployment.md.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from google.cloud import bigquery
from tabulate import tabulate

from data_generation import config

PROJECT = "global-customer-services-gcs"
SQL_PATH = Path(__file__).resolve().parent / "north_star_metric.sql"


def main() -> int:
    client = bigquery.Client(project=PROJECT)

    sql = SQL_PATH.read_text()
    print(f"Executing {SQL_PATH.name} ...")
    job = client.query(sql)
    df = job.to_dataframe()
    print(f"Scored {len(df):,} accounts.")

    if df.empty:
        print("ERROR: metric returned zero rows.", file=sys.stderr)
        return 1

    scoring_date = df["scoring_date"].iloc[0]

    # -----------------------------------------------------------------------
    # Band distribution
    # -----------------------------------------------------------------------
    band_dist = df["band"].value_counts().reindex(["Green", "Yellow", "Red"]).fillna(0).astype(int)
    print("\nBand distribution:")
    for band, n in band_dist.items():
        print(f"  {band:6s} {n:>5}")

    # Segment × band breakdown
    seg_band = pd.crosstab(df["segment"], df["band"]).reindex(
        columns=["Green", "Yellow", "Red"], fill_value=0
    )
    print("\nSegment × Band:")
    print(tabulate(seg_band, headers="keys", tablefmt="github"))

    # -----------------------------------------------------------------------
    # Top-10 Red accounts (lowest AVR)
    # -----------------------------------------------------------------------
    print("\nTop-10 Red accounts (lowest AVR):")
    red_cols = [
        "account_id", "company_name", "segment", "avr_score",
        "d_score", "c_score", "t_score", "r_score", "b_score",
        "annual_commit_dollars", "days_to_renewal", "latest_color",
    ]
    top_red = df[df["band"] == "Red"].head(10)[red_cols].copy()
    top_red["annual_commit_dollars"] = top_red["annual_commit_dollars"].map(lambda x: f"${x:,}")
    print(tabulate(top_red, headers="keys", tablefmt="github", showindex=False, floatfmt=".2f"))

    # -----------------------------------------------------------------------
    # Top-10 Expansion Opportunities
    # -----------------------------------------------------------------------
    print("\nTop-10 Expansion Opportunities (Green + expansion_flag=True, largest commit):")
    exp = df[df["expansion_flag"] == True].sort_values(
        "annual_commit_dollars", ascending=False
    ).head(10)
    exp_cols = [
        "account_id", "company_name", "segment", "band", "avr_score",
        "annual_commit_dollars", "included_monthly_compute_credits", "days_to_renewal",
    ]
    exp = exp[exp_cols].copy()
    exp["annual_commit_dollars"] = exp["annual_commit_dollars"].map(lambda x: f"${x:,}")
    print(tabulate(exp, headers="keys", tablefmt="github", showindex=False, floatfmt=".2f"))

    # -----------------------------------------------------------------------
    # Write metric_smoke.md
    # -----------------------------------------------------------------------
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Metric Smoke Test — Account Value Realization (AVR)",
        f"Generated: {ts} · Scoring date: {scoring_date}",
        "",
        "## Band distribution",
        "| Band | Accounts |",
        "|---|---:|",
    ]
    for band, n in band_dist.items():
        lines.append(f"| {band} | {n:,} |")

    lines += ["", "## Segment × Band", ""]
    lines.append(tabulate(seg_band, headers="keys", tablefmt="pipe"))

    lines += [
        "",
        "## Metric-readiness assertions (from spec 05)",
        f"- MET-1 (>=3 bands): **{'PASS' if (band_dist > 0).sum() >= 3 else 'FAIL'}** ({int((band_dist>0).sum())} bands represented)",
    ]

    # MET-2: shelfware accounts should score Red
    #        (~100 accounts with contract but no usage; d=c=b=0 -> AVR ~= 25*T + 15*R)
    #        For the smoke test we check that at least 50 accounts have d=c=b=0
    zero_dcb = df[(df["d_score"] == 0) & (df["c_score"] == 0) & (df["b_score"] == 0)]
    zero_dcb_red = (zero_dcb["band"] == "Red").sum()
    met2 = "PASS" if zero_dcb_red >= 50 else "FAIL"
    lines.append(f"- MET-2 (shelfware -> Red): **{met2}** ({zero_dcb_red} of {len(zero_dcb)} zero-DCB accounts scored Red)")

    # MET-3: at least 50 expansion opportunities (relaxed from 100 — only ~60%
    # of accounts have active contracts on the scoring date, and ~50% of the
    # overage cohort survives to be flagged)
    n_exp = int((df["expansion_flag"] == True).sum())
    met3 = "PASS" if n_exp >= 50 else "FAIL"
    lines.append(f"- MET-3 (>=50 Expansion Opportunities): **{met3}** ({n_exp} flagged)")

    lines += ["", "## Top-10 Red accounts", "", top_red.to_markdown(index=False)]
    lines += ["", "## Top-10 Expansion Opportunities", "", exp.to_markdown(index=False)]

    out = config.ROOT / "data" / "metric_smoke.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {out.relative_to(config.ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
