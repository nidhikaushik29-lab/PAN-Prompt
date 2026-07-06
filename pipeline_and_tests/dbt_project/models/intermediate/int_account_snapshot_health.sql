-- int_account_snapshot_health.sql
-- Latest health color as of each snapshot_date + whether the account had any
-- Red weeks in the trailing 30 days (used by R component).
--
-- Grain: (snapshot_date, account_id).
--
-- Health is weekly (Sundays), so "latest as of snapshot_date" = the most
-- recent Sunday <= snapshot_date. Accounts with no health rows at all get
-- NULL latest_color; the mart maps NULL → 0.5 (unknown, not-Green not-Red).

WITH snapshots AS (
    SELECT snapshot_date FROM {{ ref('int_snapshot_dates') }}
),

health_ranked AS (
    SELECT
        s.snapshot_date,
        h.account_id,
        h.health_color,
        ROW_NUMBER() OVER (
            PARTITION BY s.snapshot_date, h.account_id
            ORDER BY h.date DESC
        ) AS rn
    FROM snapshots s
    JOIN {{ ref('stg_account_health') }} h
      ON h.date <= s.snapshot_date
),

latest_color AS (
    SELECT snapshot_date, account_id, health_color AS latest_color
    FROM health_ranked
    WHERE rn = 1
),

red_flag AS (
    SELECT
        s.snapshot_date,
        h.account_id,
        LOGICAL_OR(h.health_color = 'Red') AS had_red_last_30d
    FROM snapshots s
    JOIN {{ ref('stg_account_health') }} h
      ON h.date BETWEEN DATE_SUB(s.snapshot_date, INTERVAL 30 DAY)
                    AND s.snapshot_date
    GROUP BY 1, 2
)

SELECT
    l.snapshot_date,
    l.account_id,
    l.latest_color,
    COALESCE(r.had_red_last_30d, FALSE) AS had_red_last_30d
FROM latest_color l
LEFT JOIN red_flag r
  USING (snapshot_date, account_id)
