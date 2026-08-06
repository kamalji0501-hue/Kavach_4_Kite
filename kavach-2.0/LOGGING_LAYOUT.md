# Logging Layout — Batman v3 (single root)

Last updated: 2026-07-11  
Runtime roots (default):  
- Logs: `%USERPROFILE%/Desktop/Batman Executed Data/Logs`  
- Data + reports: `%USERPROFILE%/Desktop/Batman Executed Data/Data and Reports`  
See `docs/MULTI_DEV_SETUP.md`  
Design spec: `telegram/design/logging_design.md`  
Implementation: `core/runtime_logging.py`, `core/bot_logging.py`, `core/batman_mode.py`

---

## One folder to remember

```
Desktop/Batman Executed Data/Logs/{mode}/runtime/YYYY-MM/YYYY-MM-DD/
```

(e.g. UAT: `Batman Executed Data/Logs/uat/runtime/2026-07/2026-07-11/`)

Everything lives here. No separate `logs/bots/` folder.

---

## Folder tree

```
logs/runtime/
└── 2026-06/
    └── 2026-06-02/
        ├── logs/                         ← MAIN (all robots combined)
        │   ├── all.log                   ← open this for full-day timeline
        │   ├── runtime_YYYYMMDD_….log     ← hourly windows (detail)
        │   └── runtime_*_errors.log
        ├── drishti/
        │   ├── logs/
        │   │   ├── all.log               ← open this for all DRISHTI today
        │   │   ├── drishti_YYYYMMDD_….log
        │   │   ├── nifty_websocket_ltp/
        │   │   │   └── ws_ltp_YYYYMMDD.log         ← WebSocket ticks (batch 1s)
        │   │   ├── nifty_rest_ltp/
        │   │   │   └── rest_ltp_YYYYMMDD.log       ← REST poll ticks
        │   │   └── nifty_ltp/
        │   │       └── gift_nifty_ltp_YYYYMMDD.log ← GIFT validation only

        │   └── errors/
        │       └── all_errors.log        ← all DRISHTI errors today
        ├── kavach/
        │   ├── logs/all.log
        │   └── errors/all_errors.log
        └── jagran/
            ├── logs/all.log
            └── errors/all_errors.log
        └── launchers/                    ← bulk Start/Stop .bat sessions (Phase 1)
            ├── stop_all/
            │   ├── logs/all.log          ← each Stop All run appends here
            │   └── errors/all_errors.log
            └── start_all/
                ├── logs/all.log          ← each Start All run appends here
                └── errors/all_errors.log
```

---

## Quick paths (replace date as needed)

| What | Path |
|------|------|
| **Everything today (all bots)** | `logs/runtime/2026-06/2026-06-02/logs/all.log` |
| **DRISHTI today (all)** | `logs/runtime/2026-06/2026-06-02/drishti/logs/all.log` |
| **DRISHTI errors today** | `logs/runtime/2026-06/2026-06-02/drishti/errors/all_errors.log` |
| **KAVACH today** | `logs/runtime/2026-06/2026-06-02/kavach/logs/all.log` |
| **KAVACH errors today** | `logs/runtime/2026-06/2026-06-02/kavach/errors/all_errors.log` |
| **JAGRAN today** | `logs/runtime/2026-06/2026-06-02/jagran/logs/all.log` |
| **NIFTY WebSocket tick audit** | `logs_{mode}/runtime/…/drishti/logs/nifty_websocket_ltp/ws_ltp_YYYYMMDD.log` |
| **NIFTY REST tick audit** | `logs_{mode}/runtime/…/drishti/logs/nifty_rest_ltp/rest_ltp_YYYYMMDD.log` |
| **GIFT tick audit** | `logs_{mode}/runtime/…/drishti/logs/nifty_ltp/gift_nifty_ltp_YYYYMMDD.log` |
| **Stop All launcher today** | `logs/runtime/2026-06/2026-06-02/launchers/stop_all/logs/all.log` |
| **Start All launcher today** | `logs/runtime/2026-06/2026-06-02/launchers/start_all/logs/all.log` |

---

## Line format

Runtime files:

```
HHMMSS.mmm IST | LEVEL | MODULE | STAGE | STEP | CORRELATION_ID | MESSAGE | ERROR_CODE
```

---

## Runners

| Entry | Bootstrap |
|-------|-----------|
| `run_drishti.py` | `configure_bot_logging(bot_name="drishti")` |
| `run_kavach2.py` | `configure_bot_logging(bot_name="kavach")` |
| `run_jagran.py` | `configure_bot_logging(bot_name="jagran")` |

Config: `config/settings.json` → `"logging": { "root_dir": "logs/runtime" }`

---

## Maintenance

```powershell
.venv\Scripts\python.exe scripts/migrate_logs_layout.py
.venv\Scripts\python.exe scripts/validate_log_layout.py
.venv\Scripts\python.exe scripts/prune_logs.py --days 30
```

---

*Referenced from `TESTING_PROTOCOL.md`, `AGENTS.md`.*
