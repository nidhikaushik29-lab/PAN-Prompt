-- =========================================================================
-- ddl.sql — reference DDL for the 6 tables in gcs_north_star.
-- Note: `src/bq/load.py` uses these schemas via JSON in schemas/*.json;
-- this file is kept as human-readable documentation.
-- =========================================================================

CREATE SCHEMA IF NOT EXISTS `global-customer-services-gcs.gcs_north_star`
OPTIONS(location = "US");

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.csm_reps` (
  csm_id      STRING NOT NULL,
  name        STRING NOT NULL,
  region      STRING NOT NULL,
  segment     STRING NOT NULL,
  hire_date   DATE   NOT NULL
);

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.accounts` (
  account_id     STRING NOT NULL,
  company_name   STRING NOT NULL,
  industry       STRING NOT NULL,
  rep_id         STRING NOT NULL,   -- FK → csm_reps.csm_id (name mismatch intentional)
  segment        STRING NOT NULL,
  signup_date    DATE   NOT NULL
);

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.contracts` (
  contract_id                       STRING NOT NULL,
  account_id                        STRING NOT NULL,
  start_date                        DATE   NOT NULL,
  end_date                          DATE   NOT NULL,
  annual_commit_dollars             INT64  NOT NULL,
  included_monthly_compute_credits  INT64  NOT NULL,
  contract_type                     STRING NOT NULL
);

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.support_tickets` (
  ticket_id     STRING NOT NULL,
  account_id    STRING NOT NULL,
  opened_date   DATE   NOT NULL,
  closed_date   DATE,
  severity      INT64  NOT NULL,   -- 1=critical, 2=high, 3=low
  product_area  STRING NOT NULL,
  status        STRING NOT NULL
);

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.account_health` (
  account_id                STRING NOT NULL,
  date                      DATE   NOT NULL,
  health_color              STRING NOT NULL,
  compute_credits_consumed  INT64  NOT NULL
)
PARTITION BY date;

CREATE OR REPLACE TABLE `global-customer-services-gcs.gcs_north_star.daily_usage_logs` (
  log_id                    STRING NOT NULL,
  account_id                STRING NOT NULL,
  date                      DATE   NOT NULL,
  compute_credits_consumed  INT64  NOT NULL
)
PARTITION BY date;
