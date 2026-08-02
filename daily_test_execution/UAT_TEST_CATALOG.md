# UAT test catalog (UAT-D00 … UAT-D30)

Executable via `tests/test_uat_daily_matrix.py` and `scripts/run_uat_daily_test_suite.py`.

Full protocol: **`UAT_DAILY_TEST_PROTOCOL.md`**

| ID | Category | What it verifies |
|----|----------|------------------|
| UAT-D00 | config | `batman_mode.json` = uat |
| UAT-D01 | book | Screenshot or `positions.json` in `uat/deployed_positions/` |
| UAT-D02 | book | `positions.json` has 4 iron-condor legs |
| UAT-D03 | auth | JWT in `data/access_token.json` not expired |
| UAT-D04 | book | `validate_fixture.py` — Dhan symbols/securityIds |
| UAT-D05 | broker | ShadowBroker loads 4 rows from book |
| UAT-D06 | broker | Virtual MARKET BUY → TRADED on shadow book |
| UAT-D07 | ltp | NIFTY cache fresh (market hours; SKIP off-hours) |
| UAT-D08 | bots | DRISHTI RUNNING + lock |
| UAT-D09 | bots | KAVACH RUNNING + lock |
| UAT-D10 | bots | JAGRAN RUNNING + lock |
| UAT-D11 | telegram | `phase1_bot_check.py` all PASS |
| UAT-D12 | logs | KAVACH `logs_uat/.../all.log` no ERROR (OCR ignored if cursor_chat) |
| UAT-D13 | logs | DRISHTI `logs_uat/.../all.log` no ERROR |
| UAT-D14 | kavach | Register `wizard_entry` smoke (mocked, no OCR block) |
| UAT-D15 | kavach | All menu handlers wired (incl. Environment) |
| UAT-D16 | kavach | `/environment` command |
| UAT-D17 | kavach | `/positions` formats shadow book |
| UAT-D18 | kavach | `/status` command |
| UAT-D19 | kavach | `/ato_status` command |
| UAT-D20 | perf | OCR ingest &lt; 120s or skip if no screenshot |
| UAT-D21 | ato | ATO deployment state recorded (pre-register or armed) |
| UAT-D22 | pytest | UAT pytest subset green |
| UAT-D23 | book | **Dynamic expiry** parse from `positions.json` (any weekly) |
| UAT-D24 | book | Instrument master resolves all 4 legs for fixture expiry |
| UAT-D25 | auth | Dhan **fundlimit** REST (JWT connectivity) |
| UAT-D26 | ltp | **NIFTY REST** `marketfeed/ltp` one-shot (market hours) |
| UAT-D27 | ltp | **Option FNO LTP** for all 4 legs via securityId (market hours) |
| UAT-D28 | logs | JAGRAN log scan (no ERROR) |
| UAT-D29 | kavach | Position enrich fills premiums from fixture |
| UAT-D30 | book | Valid book source (`cursor_chat` preferred) |

## Telegram buttons (coverage map)

| Button | Case |
|--------|------|
| Register | UAT-D14 |
| Positions | UAT-D17, D29 |
| ATO Status | UAT-D19 |
| Legs | pytest `test_kavach_scenarios` (D22) |
| Status | UAT-D18 |
| Environment | UAT-D16 |
| Funds | menu map UAT-D15 + scenarios |
| Pause / Resume / Start Algo | UAT-D15 + scenarios |
| Batman Complete | UAT-D15 + cleanup tests |

## Performance / live feed metrics (Excel `metrics_json`)

- `ocr_ms` — Sensibull OCR duration
- `fill_ms` — shadow order fill time
- `ltp`, `age_seconds` — DRISHTI cache
- `nifty_rest_ltp` — D26 REST index
- `option_ltps` — D27 per-leg FNO LTP
- `screenshot_mtime` — latest screenshot timestamp
- `log_path`, `error_lines`, `ocr_filtered` — log scans

## Logging

Each suite run writes:

- `daily_test_execution/logs/YYYY-MM/YYYY-MM-DD/daily_suite_{run_id}.log`
- `daily_test_execution/logs/YYYY-MM/YYYY-MM-DD/all.log`
