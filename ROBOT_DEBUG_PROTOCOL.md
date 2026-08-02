# Robot Debug Protocol

Short operator commands → agent owns diagnosis, fix, restart, verify.

## Voice / chat commands

| Say this | Agent does |
|----------|------------|
| **debug drishti** | Diagnose DRISHTI process + logs → fix → restart if needed |
| **debug kavach** | Same for KAVACH |
| **debug jagran** | Same for JAGRAN |
| **diagnose all bots** | All three + summary table |
| **look into error for kavach** | Same as debug kavach |

No need to paste log paths — agent resolves `logs/runtime/YYYY-MM/YYYY-MM-DD/` automatically (IST).

## Tool

```powershell
.venv\Scripts\python.exe scripts/diagnose_robot.py drishti
.venv\Scripts\python.exe scripts/diagnose_robot.py kavach --date 2026-06-02
```

## Log locations (single folder)

```
logs/runtime/2026-06/2026-06-02/
├── logs/all.log
├── drishti/logs/all.log
├── drishti/errors/all_errors.log
├── kavach/logs/all.log
├── kavach/errors/all_errors.log
├── jagran/logs/all.log
└── jagran/errors/all_errors.log
```

## Resilience (runners)

| Bot | Restart policy |
|-----|----------------|
| DRISHTI | Infinite restart loop (`run_drishti.py`) |
| KAVACH | Infinite restart loop (`run_kavach.py`) |
| JAGRAN | Infinite restart loop (`run_jagran.py`) |

Cursor rule: `.cursor/rules/batman-debug-robot.mdc`
