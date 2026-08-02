# UAT daily test protocol (focused E2E)

Run **every trading day** after UAT code changes or before Register. Goal: document PASS/FAIL/SKIP with evidence in Excel + logs.

## Operator sequence (market hours)

1. `Mode\Set-UAT.bat`
2. Paste Sensibull screenshot in Cursor → `positions.json` updated (`UAT_CHAT_POSITIONS.md`)
3. DRISHTI: fresh JWT → `data/access_token.json`
4. `Execution\Start Bots\Phase 1 Start All Robots.bat` → wait **180s** → RUNNING
5. `Execution\Run Daily UAT Test Suite.bat` (or script below)
6. Open `daily_test_execution/LATEST_RUN.md` — fix any **FAIL** before Register

## Agent command

```powershell
Mode\Set-UAT.bat
.venv\Scripts\python.exe scripts\run_uat_daily_test_suite.py
```

Flags:

| Flag | Use |
|------|-----|
| `--skip-bots` | Laptop without bots running (dev only) |
| `--skip-slow` | Quick smoke (skips validate_fixture, phase1_check, OCR, pytest, instrument resolve, live REST) |
| `--with-start` | Agent starts Phase 1 before tests |

## Artifacts (every run)

| Artifact | Path |
|----------|------|
| Excel matrix | `daily_test_execution/test_matrix.xlsx` (Matrix + `Daily_YYYY-MM-DD`) |
| Latest summary | `daily_test_execution/LATEST_RUN.md` |
| **Suite log (this run)** | `daily_test_execution/logs/YYYY-MM/YYYY-MM-DD/daily_suite_{run_id}.log` |
| **Suite log (day rollup)** | `daily_test_execution/logs/YYYY-MM/YYYY-MM-DD/all.log` |
| Bot runtime logs | `logs_uat/runtime/YYYY-MM/YYYY-MM-DD/{drishti,kavach,jagran}/` |

## Catalog (31 cases: UAT-D00 … UAT-D30)

See `UAT_TEST_CATALOG.md`. Categories:

- **config / book** — mode, screenshot, positions.json, dynamic expiry, cursor_chat source
- **auth** — JWT + fundlimit REST
- **broker** — ShadowBroker load + virtual fill
- **ltp** — NIFTY cache (DRISHTI), NIFTY REST, **option FNO marketfeed** (4 legs from fixture)
- **bots** — DRISHTI / KAVACH / JAGRAN RUNNING + lock
- **telegram** — phase1_bot_check
- **logs** — KAVACH / DRISHTI / JAGRAN ERROR scan (KAVACH ignores stale OCR errors when `cursor_chat` book active)
- **kavach** — Register smoke, all menu buttons, commands, enrich
- **pytest** — UAT-related test subset

## Live feed cases (market hours only)

| ID | What |
|----|------|
| UAT-D07 | `data/nifty_ltp_cache.json` fresh (DRISHTI poller) |
| UAT-D26 | `POST /marketfeed/ltp` NIFTY index |
| UAT-D27 | `POST /marketfeed/ltp` NSE_FNO — all 4 legs from current `positions.json` expiry |

Off-hours: D07/D26/D27 **SKIP** (not FAIL).

## FAIL remediation map

| Case | Typical fix |
|------|-------------|
| UAT-D03 / D25 | DRISHTI → Update Token |
| UAT-D07 | Start DRISHTI; check duplicate instance / 429 |
| UAT-D08–D10 | Stop All → Start All; clear stale lock |
| UAT-D12 | Real ERROR in KAVACH log; if only OCR + cursor_chat book, should PASS (filtered) |
| UAT-D24 / D27 | Wrong expiry in fixture; refresh instrument master |
| UAT-D30 | Write `positions.json` via Cursor chat shortcut |

## pytest mirror

```powershell
.venv\Scripts\python.exe -m pytest tests/test_uat_daily_matrix.py -q
```

One test per catalog case (same runners as the suite).

## After code changes

Per `TESTING_PROTOCOL.md`: quality gates → daily suite → read suite log + `logs_uat` bot logs → fix → re-run (max 4 cycles).
