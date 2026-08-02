# Daily UAT test execution

Automated E2E checks for UAT mode (ShadowBroker + Sensibull screenshot + live NIFTY LTP).

## Files

| File | Purpose |
|------|---------|
| test_matrix.xlsx | Cumulative Matrix sheet + Daily_YYYY-MM-DD per run day |
| LATEST_RUN.md | Last run summary and full path to Excel |
| UAT_TEST_CATALOG.md | All case IDs UAT-D00 through UAT-D30 |
| UAT_DAILY_TEST_PROTOCOL.md | Daily operator + agent procedure |
| logs/YYYY-MM/YYYY-MM-DD/ | Per-run suite logs + daily all.log |

## Run

```powershell
Mode\Set-UAT.bat
Execution\Run Daily UAT Test Suite.bat
```

## Agent

UAT_E2E_AGENT.md — autonomous loop updates this folder after each run.
