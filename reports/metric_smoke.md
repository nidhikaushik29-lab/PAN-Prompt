# Metric Smoke Test — Account Value Realization (AVR)
Generated: 2026-07-04 03:10 UTC · Scoring date: 2026-01-31

## Band distribution
| Band | Accounts |
|---|---:|
| Green | 232 |
| Yellow | 219 |
| Red | 158 |

## Segment × Band

| segment    |   Green |   Yellow |   Red |
|:-----------|--------:|---------:|------:|
| Enterprise |      76 |       87 |    74 |
| Mid-Market |     156 |      132 |    84 |

## Metric-readiness assertions (from spec 05)
- MET-1 (>=3 bands): **PASS** (3 bands represented)
- MET-2 (shelfware -> Red): **PASS** (72 of 72 zero-DCB accounts scored Red)
- MET-3 (>=50 Expansion Opportunities): **PASS** (76 flagged)

## Top-10 Red accounts

| account_id   | company_name                    | segment    |   avr_score |   d_score |   c_score |   t_score |   r_score |   b_score | annual_commit_dollars   |   days_to_renewal | latest_color   |
|:-------------|:--------------------------------|:-----------|------------:|----------:|----------:|----------:|----------:|----------:|:------------------------|------------------:|:---------------|
| ACCT-000699  | Williams, Chen and Wright       | Enterprise |        11.4 |         0 |         0 |  0.306667 |      0.25 |         0 | $1,453,000              |                 1 | Red            |
| ACCT-000597  | Velazquez-Russell               | Enterprise |        11.4 |         0 |         0 |  0.306667 |      0.25 |         0 | $1,964,000              |                 1 | Red            |
| ACCT-000047  | Anderson, Johnston and Schwartz | Enterprise |        11.8 |         0 |         0 |  0.32     |      0.25 |         0 | $1,457,000              |                 1 | Red            |
| ACCT-000948  | West, Carter and Pace           | Enterprise |        13.1 |         0 |         0 |  0.373333 |      0.25 |         0 | $1,163,000              |                 1 | Red            |
| ACCT-000608  | Kirby, Miller and Thompson      | Enterprise |        13.1 |         0 |         0 |  0.373333 |      0.25 |         0 | $1,788,000              |                 1 | Red            |
| ACCT-000907  | Strong, Kim and Miranda         | Enterprise |        13.1 |         0 |         0 |  0.373333 |      0.25 |         0 | $827,000                |                 1 | Red            |
| ACCT-000038  | Ellis Inc                       | Enterprise |        13.1 |         0 |         0 |  0.373333 |      0.25 |         0 | $1,619,000              |                 1 | Red            |
| ACCT-000864  | Wagner, Pierce and Gray         | Enterprise |        13.1 |         0 |         0 |  0.373333 |      0.25 |         0 | $1,433,000              |                 1 | Red            |
| ACCT-000391  | Hall, Williams and Mason        | Mid-Market |        13.8 |         0 |         0 |  0.4      |      0.25 |         0 | $111,000                |                 1 | Red            |
| ACCT-000182  | Gonzalez-Bryant                 | Mid-Market |        13.8 |         0 |         0 |  0.4      |      0.25 |         0 | $127,000                |                 1 | Red            |

## Top-10 Expansion Opportunities

| account_id   | company_name                 | segment    | band   |   avr_score | annual_commit_dollars   |   included_monthly_compute_credits |   days_to_renewal |
|:-------------|:-----------------------------|:-----------|:-------|------------:|:------------------------|-----------------------------------:|------------------:|
| ACCT-000744  | White-Eaton                  | Enterprise | Yellow |        73.3 | $1,986,000              |                            3310000 |                 1 |
| ACCT-000763  | Madden-Wright                | Enterprise | Green  |        75.5 | $1,723,000              |                            2871667 |                 1 |
| ACCT-000752  | Clark, Stephens and Luna     | Enterprise | Green  |        77.3 | $1,561,000              |                            2601667 |                 1 |
| ACCT-000829  | Norman-Hunt                  | Enterprise | Green  |        85.5 | $1,445,000              |                            2408333 |                90 |
| ACCT-000838  | Curtis-Baker                 | Enterprise | Green  |        78.5 | $1,410,000              |                            2350000 |                 1 |
| ACCT-000688  | Miranda, Russell and Mejia   | Enterprise | Green  |        89.6 | $1,398,000              |                            2330000 |                29 |
| ACCT-000393  | Davis Group                  | Enterprise | Green  |        77.2 | $1,219,000              |                            2031667 |                 1 |
| ACCT-000901  | Holmes Group                 | Enterprise | Yellow |        72.1 | $1,206,000              |                            2010000 |                 1 |
| ACCT-000887  | Taylor Group                 | Enterprise | Green  |        76.1 | $1,113,000              |                            1855000 |                 1 |
| ACCT-000912  | Stewart, Robinson and Keller | Enterprise | Yellow |        73.7 | $1,017,000              |                            1695000 |                 1 |
