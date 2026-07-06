# QA Report — GCS North Star Dataset
Generated: 2026-07-04 22:36 UTC · Seed: 42

## Summary
Total checks: 26 · Passed: 26 · Failed: 0 · Overall: **PASS**

## Row Counts
| Table | Rows |
|---|---:|
| `csm_reps` | 50 |
| `accounts` | 1,000 |
| `contracts` | 1,200 |
| `support_tickets` | 27,317 |
| `account_health` | 56,417 |
| `daily_usage_logs` | 227,676 |

## Checks
| ID | Description | Status | Detail |
|---|---|---|---|
| COUNT-csm_reps | csm_reps rows in [50, 50] | PASS | actual=50 |
| COUNT-accounts | accounts rows in [1,000, 1,000] | PASS | actual=1,000 |
| COUNT-contracts | contracts rows in [1,080, 1,320] | PASS | actual=1,200 |
| COUNT-support_tickets | support_tickets rows in [22,500, 37,500] | PASS | actual=27,317 |
| COUNT-account_health | account_health rows in [40,000, 60,000] | PASS | actual=56,417 |
| COUNT-daily_usage_logs | daily_usage_logs rows in [160,000, 240,000] | PASS | actual=227,676 |
| RI-1 | RI-1: FK integrity >= 100.00% | PASS | actual_valid_frac=100.0000% |
| RI-2 | RI-2: FK integrity >= 100.00% | PASS | actual_valid_frac=100.0000% |
| RI-3 | RI-3: FK integrity >= 100.00% | PASS | actual_valid_frac=100.0000% |
| RI-4 | RI-4: FK integrity >= 100.00% | PASS | actual_valid_frac=100.0000% |
| RI-5 | RI-5: FK integrity >= 99.85% | PASS | actual_valid_frac=99.9122% |
| SEG-1 | SEG-1: account segment matches CSM segment | PASS | mismatches=0 |
| SEG-2 | SEG-2: Enterprise fraction in accounts ~40% (±3pp) | PASS | actual=40.00% |
| SEG-3 | SEG-3: Enterprise fraction in csm_reps ~40% (±5pp) | PASS | actual=40.00% |
| EC-1 | EC-1: Spike & Drop accounts (month1 >= 85% of total) >= 45 | PASS | actual=50 |
| EC-2 | EC-2: Shelfware accounts (contract, no usage) >= 90 | PASS | actual=100 |
| EC-3 | EC-3: Consistent-Overage accounts (>=6 months >120% of allotment) >= 140 | PASS | actual=153 |
| EC-4 | EC-4: Accounts with overlapping active contracts >= 25 | PASS | actual=88 |
| EC-5a | EC-5a: Orphan usage logs (unknown account_id) >= 150 | PASS | actual=200 |
| EC-5b | EC-5b: Out-of-window usage logs (no covering contract) >= 75 | PASS | actual=100 |
| EC-6 | EC-6: Approaching-cap accounts (>=6 months in [0.80, 1.20) x allotment) >= 70 | PASS | actual=103 |
| DIST-1 | DIST-1: severity mix within 5pp of target | PASS | sev1=3.19%, sev2=12.23%, sev3=84.57% |
| DIST-2 | DIST-2: Enterprise NEW annual_commit in [$200K, $2M] | PASS | min=$201,000, max=$1,995,000 |
| DIST-3 | DIST-3: Mid-Market NEW annual_commit in [$25K, $200K] | PASS | min=$25,000, max=$199,000 |
| DIST-4 | DIST-4: health_color values only in {Green, Yellow, Red} | PASS | seen=['Green', 'Red', 'Yellow'] |
| DIST-5 | DIST-5: all contract start_dates in [WINDOW_START, WINDOW_END] | PASS | out_of_window_starts=0 |
