# Incident tracker — domain error files (Phase 1+)

Last updated: 2026-06-25  
**Knowledge base:** `docs/INCIDENT_MANAGEMENT_SYSTEM.md` · `docs/incidents/registry.json`  
Implementation: `core/incident_tracker.py`, `core/incident_knowledge.py`, `core/incident_log_handler.py`  
Telegram / JAGRAN routing: `bat_telegram/incident_publisher.py` (unchanged allowlist + new `launcher` scenarios)

---

## Purpose

Capture **every serious error** into **separate daily files per domain** so you can:

- See **what** failed, **when** (IST), and **likely why** (`cause_hint`)
- Track **repeats** (`repeat_count`, status `TRIGGERED` / `REPEAT` / `SUPPRESSED`)
- Compare **DRISHTI vs KAVACH vs JAGRAN vs Start/Stop launchers** when analysing infra
- Mirror rows into the **global** `incident_ledger_YYYYMMDD.csv` (existing JAGRAN ledger)

---

## Six domains (Phase 1 + main runtime)

| Domain | What it covers | Typical scenarios |
|--------|----------------|-------------------|
| **drishti** | `run_drishti.py`, DRISHTI handlers, NIFTY feed | `log_error`, `ltp_fetch_failure`, … |
| **kavach** | `run_kavach.py`, ATO, register | `log_error`, ATO LTP stale, … |
| **jagran** | `run_jagran.py`, incident routing | `log_error`, … |
| **main** | `main.py` five-bot orchestrator | `log_error`, module offline, heartbeat |
| **start_all** | `Phase 1 Start All`, `phase1_start_all.py` | `start_all_timeout`, `start_all_abort`, … |
| **stop_all** | `Phase 1 Stop All`, `phase1_stop_all.py` | `stop_all_failure`, … |

When new bots join Phase 1, add a domain in `INCIDENT_DOMAINS` in `core/incident_tracker.py` and document here.

---

## File layout

```
data/analytics/incidents/
  incident_ledger_YYYYMMDD.csv          ← global (existing)
  incident_ledger_YYYYMMDD.log
  by_domain/
    drishti/
      incidents_YYYYMMDD.csv            ← structured rows
      errors_YYYYMMDD.log               ← human tail-friendly
    kavach/
    jagran/
    main/
    start_all/
    stop_all/
  open_registry.json                    ← open operator_status + repeat_jagran_sent
  dashboard_YYYYMMDD.xlsx               ← weekly export (incident_dashboard.py)
```

### Domain CSV columns

`ts_ist`, `date_ist`, `incident_id`, `status`, `operator_status`, `event_type`, `domain`, `module`, `scenario`, `severity`, `error_type`, `message`, `cause_hint`, `repeat_count`, `context_json`

**status:** `TRIGGERED`, `REPEAT`, `SUPPRESSED` (dedup within 120s), `RECOVERED`  
**operator_status:** `open` while active, `closed` on recovery  
**event_type:** `incident` or `recovery`

Open incidents persist across restarts in `data/analytics/incidents/open_registry.json`.

---

## How errors are captured

| Source | Mechanism |
|--------|-----------|
| Bot processes | `DomainIncidentHandler` on root logger (ERROR+) via `configure_bot_logging` |
| Start/Stop All failure | `record_incident` in `phase1_start_all.py` / `phase1_stop_all.py` + JAGRAN for critical launcher cases |
| Launcher session log | `LauncherSessionLogger.error` / `.warning` → domain `start_all` / `stop_all` |
| Manual / code | `record_incident()`, `record_exception()`, `resolve_domain_incident()` |

Existing `publish_incident()` call sites still work; domain files add **parallel** structured tracking.

---

## Operator / agent commands

```powershell
# Knowledge registry (RCA, dashboard, lessons)
.venv\Scripts\python.exe scripts\incident_mgmt.py report
.venv\Scripts\python.exe scripts\incident_mgmt.py list
.venv\Scripts\python.exe scripts\incident_mgmt.py show INC-2026-016
.venv\Scripts\python.exe scripts\incident_mgmt.py search "websocket stale"

# Runtime domain CSV (auto ERROR+ capture)
.venv\Scripts\python.exe scripts\incident_report.py
.venv\Scripts\python.exe scripts\incident_report.py --open-only
.venv\Scripts\python.exe scripts\incident_dashboard.py --days 7
.venv\Scripts\python.exe scripts\incident_close.py --list
.venv\Scripts\python.exe scripts\incident_close.py --incident-id kavach::log_error
```

**Simulator:** `simulator/app.py` attaches the same **main** domain incident handler as `main.py` (local multi-bot UI errors land in `by_domain/main/`).

Or double-click: `Execution\Incident Dashboard.bat`  
Excel output: `data/analytics/incidents/dashboard_YYYYMMDD.xlsx`

---

## Weekly dashboard (Excel)

`scripts/incident_dashboard.py` builds:

| Sheet | Content |
|-------|---------|
| Summary | Period, totals, open count |
| By_Domain | Row counts per domain |
| Top_Scenarios | Sorted by max `repeat_count` (repeating issues) |
| Open_Now | `open_registry.json` |
| All_Events | Raw incident rows for the week |

---

## JAGRAN routing

| Trigger | When |
|---------|------|
| Critical launcher failure | `notify_jagran=True` on stop/start all failure |
| **Repeat escalation** | Same scenario repeats **≥ 3** times → Telegram via `incident_repeat_escalation` (once per open incident) |

Bot-domain errors are recorded to **files first**; explicit `publish_incident` paths in bot code still apply.

---

## Related docs

- `docs/INCIDENT_MANAGEMENT_SYSTEM.md` — **knowledge registry, lifecycle, RCA template**
- `docs/incidents/KNOWLEDGE_BASE.md` — cross-cutting lessons
- `LOGGING_LAYOUT.md` — runtime logs under `logs/runtime/`
- `Execution/PHASE1_ROBOT_LAUNCHER.md` — bulk start/stop
- `CONTEXT.md` §3.1
- `JAGRAN_ERROR_MATRIX.md` — Telegram allowlist detail
