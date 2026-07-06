"""Load the 6 generated CSVs into BigQuery.

Spec references: 06-bigquery-deployment.md.
Requires: `gcloud auth application-default login` completed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from google.cloud import bigquery

from data_generation import config

PROJECT = "global-customer-services-gcs"
DATASET = "gcs_north_star"
LOCATION = "US"

TABLES = [
    "csm_reps",
    "accounts",
    "contracts",
    "support_tickets",
    "account_health",
    "daily_usage_logs",
]

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def _load_schema(name: str) -> list[bigquery.SchemaField]:
    fields = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    return [
        bigquery.SchemaField(
            f["name"], field_type=f["type"], mode=f.get("mode", "NULLABLE")
        )
        for f in fields
    ]


def main() -> int:
    client = bigquery.Client(project=PROJECT)
    dataset_ref = f"{PROJECT}.{DATASET}"

    # Ensure dataset exists (idempotent — no-op if pre-created by `make bq-dataset`)
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset {dataset_ref} already exists.")
    except Exception:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = LOCATION
        ds.default_table_expiration_ms = None   # override 60-day sandbox default
        client.create_dataset(ds)
        print(f"Created dataset {dataset_ref} in {LOCATION}.")

    for tbl in TABLES:
        csv_path = config.DATA_DIR / f"{tbl}.csv"
        if not csv_path.exists():
            print(f"ERROR: missing {csv_path}. Run `make generate` first.", file=sys.stderr)
            return 1

        schema = _load_schema(tbl)
        table_ref = f"{dataset_ref}.{tbl}"

        job_config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            allow_quoted_newlines=True,
        )

        with open(csv_path, "rb") as f:
            job = client.load_table_from_file(f, table_ref, job_config=job_config)

        print(f"Loading {tbl} ...", flush=True)
        job.result()   # wait
        loaded_tbl = client.get_table(table_ref)
        print(f"  {tbl}: {loaded_tbl.num_rows:,} rows")

    print("\nLoad complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
