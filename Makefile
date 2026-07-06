# GCS-NorthStar submission — reproducible pipeline.
# Full end-to-end: generate synthetic data -> validate -> load BigQuery ->
# raw metric SQL -> dbt-materialized marts + tests -> Streamlit dashboard.
# Every target is idempotent.

PY := python3
VENV := .venv
VENV_PY := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

# Change these three lines to point at your own GCP project / dataset if you
# want to run the BigQuery half of the pipeline. The dashboard app.py and the
# dbt profiles.yml hard-code the same project id — see README.md § BigQuery.
PROJECT := global-customer-services-gcs
DATASET := gcs_north_star
LOCATION := US

# gcloud/bq CLI. gcloud requires Python 3.10+; adjust CLOUDSDK_PYTHON if your
# gcloud install is elsewhere. The Makefile does NOT require gcloud for the
# generate/validate targets — only for `make load`, `make metric`, `make dbt-*`.
GCLOUD := gcloud
BQ     := bq

# dbt: point at the repo-local profiles.yml, suppress Py 3.9 EOL warnings
DBT             := DBT_PROFILES_DIR=pipeline_and_tests/dbt_project PYTHONWARNINGS=ignore $(VENV)/bin/dbt
DBT_PROJECT_DIR := pipeline_and_tests/dbt_project

# Streamlit dashboard
STREAMLIT      := PYTHONWARNINGS=ignore $(VENV)/bin/streamlit
DASHBOARD_DIR  := dashboard
DASHBOARD_PORT := 8501

.PHONY: help setup generate validate load metric all clean bq-auth bq-init \
        dbt-deps dbt-run dbt-test dbt-build dbt-docs phase2 dashboard phase3 pptx

help:
	@echo "GCS-NorthStar targets:"
	@echo "  Phase 1 — raw pipeline"
	@echo "    make setup        Create .venv and install Python deps"
	@echo "    make generate     Generate 6 synthetic CSVs into data/raw/"
	@echo "    make validate     Run QA harness (26 assertions) -> reports/qa_report.md"
	@echo "    make bq-auth      One-time gcloud application-default login"
	@echo "    make bq-init      Verify gcloud auth + set project"
	@echo "    make load         Load 6 CSVs into BigQuery"
	@echo "    make metric       Run north_star_metric.sql, print top results"
	@echo "    make all          Phase 1 end-to-end"
	@echo "  Phase 2 — dbt"
	@echo "    make dbt-deps     Install dbt_utils"
	@echo "    make dbt-run      Build 14 dbt models (staging + intermediate + marts)"
	@echo "    make dbt-test     Run all dbt tests (~122)"
	@echo "    make dbt-build    dbt-deps + dbt-run + dbt-test in order"
	@echo "    make dbt-docs     Generate + serve dbt docs on :8080"
	@echo "    make phase2       generate + validate + load + dbt-build"
	@echo "  Phase 3 — dashboard"
	@echo "    make dashboard    Launch Streamlit exec dashboard on port $(DASHBOARD_PORT)"
	@echo "    make phase3       phase2 + dashboard"
	@echo "  Housekeeping"
	@echo "    make clean        Remove .venv, generated data, dbt artifacts"

setup:
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	@echo "Setup complete. Activate: source $(VENV)/bin/activate"

generate:
	$(VENV_PY) -m data_generation.main

validate:
	$(VENV_PY) -m pipeline_and_tests.validate.quality_checks

bq-auth:
	$(GCLOUD) auth application-default login

bq-init:
	@command -v $(GCLOUD) >/dev/null 2>&1 || (echo "gcloud not on PATH. See README.md § BigQuery." && exit 1)
	$(GCLOUD) config set project $(PROJECT)
	@$(GCLOUD) auth application-default print-access-token >/dev/null 2>&1 || \
		(echo "Need ADC. Run: make bq-auth" && exit 1)
	@echo "gcloud project set, ADC valid."

load: bq-init
	$(VENV_PY) -m pipeline_and_tests.bq.load

metric:
	$(VENV_PY) -m pipeline_and_tests.bq.run_metric

all: setup generate validate load metric

dbt-deps:
	$(DBT) deps --project-dir $(DBT_PROJECT_DIR)

dbt-run:
	$(DBT) run --project-dir $(DBT_PROJECT_DIR)

dbt-test:
	$(DBT) test --project-dir $(DBT_PROJECT_DIR)

dbt-build: dbt-deps
	$(DBT) build --project-dir $(DBT_PROJECT_DIR)

dbt-docs:
	$(DBT) docs generate --project-dir $(DBT_PROJECT_DIR)
	$(DBT) docs serve   --project-dir $(DBT_PROJECT_DIR) --port 8080

phase2: generate validate load dbt-build

dashboard:
	@echo "Launching dashboard on http://localhost:$(DASHBOARD_PORT)  (Ctrl+C to stop)"
	$(STREAMLIT) run $(DASHBOARD_DIR)/app.py --server.port $(DASHBOARD_PORT)

phase3: phase2 dashboard

clean:
	rm -rf $(VENV) data/raw/*.csv reports/qa_report.md
	rm -rf $(DBT_PROJECT_DIR)/target $(DBT_PROJECT_DIR)/dbt_packages $(DBT_PROJECT_DIR)/logs
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
