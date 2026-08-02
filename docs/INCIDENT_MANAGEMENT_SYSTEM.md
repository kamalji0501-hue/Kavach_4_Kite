# Incident Management System

**Single source of truth for engineering incidents** — complements the runtime error capture in `core/incident_tracker.py`.

| Layer | Purpose | Location |
|-------|---------|----------|
| **Knowledge registry** | RCA, fixes, validation, lessons learned | `docs/incidents/registry.json` |
| **Human dashboard** | Index + metrics | `docs/incidents/REGISTRY.md` |
| **Excel registry** | Commentary, expiry, all issues (multi-sheet) | `docs/incidents/incident_registry.xlsx` |
| **Per-incident records** | Full template detail | `docs/incidents/records/INC-*.md` |
| **Knowledge base** | Cross-cutting lessons | `docs/incidents/KNOWLEDGE_BASE.md` |
| **Runtime tracker** | Auto ERROR+ capture, daily CSV | `data/analytics/incidents/by_domain/` |

---

## When to create or update an incident

Create or update a **knowledge incident** when you discover:

- Startup / shutdown failure
- WebSocket or REST feed failure
- Broker / token / ShadowBroker issue
- Configuration or state-path bug
- ATO / register / simulator defect
- Testing or validation gap
- Documentation inconsistency with behavior

**Do not wait for operator approval.** If it is significant, record it.

---

## Incident ID format

| Pattern | Example | Use |
|---------|---------|-----|
| `INC-2026-STAB-NN` | `INC-2026-STAB-04` | Stabilization sprint (2026-06-12) |
| `INC-2026-NNN` | `INC-2026-016` | Sequential engineering incidents |

Link runtime auto-captured IDs (`kavach::log_error`) in the `runtime_incident_ids` field.

---

## Lifecycle (mandatory)

```
new → under_investigation → root_cause_identified → fix_implemented
  → testing → regression_testing → stress_testing → verified → closed
```

Do **not** mark `closed` without validation evidence and `validation_cycles >= 2` for production-impacting issues.

---

## Categories

`robot` · `infrastructure` · `broker` · `market_data` · `configuration` · `runtime` · `testing` · `documentation`

---

## Full template fields

Every record in `registry.json` includes:

Incident ID, title, category, subsystem, robot affected, dates, lifecycle, severity, priority, environment, frequency, symptoms, business/technical/trading impact, root cause, contributing factors, investigation, files/modules, logs, fix, fix rationale, regression risk, validation, stress tests, validation cycles, remaining risks, related incidents, runtime IDs, preventive measures, lessons learned, future recommendations, owner, last updated.

See any file under `docs/incidents/records/` for a rendered example.

---

## Agent / operator commands

```powershell
# Initialize or refresh seed (first time)
.venv\Scripts\python.exe scripts\incident_mgmt.py seed

# Dashboard JSON
.venv\Scripts\python.exe scripts\incident_mgmt.py dashboard

# List all / open only
.venv\Scripts\python.exe scripts\incident_mgmt.py list
.venv\Scripts\python.exe scripts\incident_mgmt.py list --open-only

# Show one incident
.venv\Scripts\python.exe scripts\incident_mgmt.py show INC-2026-016

# Duplicate / regression search before creating new incident
.venv\Scripts\python.exe scripts\incident_mgmt.py search "websocket stale failover"

# Regenerate markdown from JSON
.venv\Scripts\python.exe scripts\incident_mgmt.py export

# Excel workbook (Commentary + Fixture_Expiry + All_Issues sheets)
.venv\Scripts\python.exe scripts\incident_mgmt.py export-excel
# Or: Execution\Export Incident Registry Excel.bat
# File: docs/incidents/incident_registry.xlsx

# Close runtime CSV incidents linked to closed knowledge records
.venv\Scripts\python.exe scripts\incident_mgmt.py sync-runtime

# Session summary
.venv\Scripts\python.exe scripts\incident_mgmt.py report

# Verify every closed incident fix exists in code (static + runtime + pytest)
.venv\Scripts\python.exe scripts\verify_incident_fixes.py
# Report: data/analytics/incidents/FIX_VERIFICATION.md
```

**Runtime tracker (unchanged):**

```powershell
.venv\Scripts\python.exe scripts\incident_report.py
.venv\Scripts\python.exe scripts\incident_dashboard.py --days 7
```

---

## Duplicate detection workflow

1. Run `incident_mgmt.py search "<symptoms or error message>"`
2. If match ≥ 40%: update existing record (regression) — link `related_incidents`
3. If new: add to `registry.json` via `upsert_incident()` or edit JSON + `export`
4. After fix: update lifecycle, validation fields, close runtime via `sync-runtime`

---

## Documentation sync

When an incident changes system behavior, also update:

- `docs/STABILIZATION_SPRINT.md` (if reliability sprint item)
- `SESSION_CAPTURE_LOG.md` (session bridge)
- `LOGGING_LAYOUT.md` / runbooks if observability changed
- `AGENTS.md` / `INCIDENT_TRACKER.md` pointers

---

## Related docs

- `INCIDENT_TRACKER.md` — runtime domain CSV layout
- `docs/STABILIZATION_SPRINT.md` — STAB-01…15 detail
- `docs/BATMAN_FEED_OPERATOR_RUNBOOK.md` — feed recovery ops
- `TESTING_PROTOCOL.md` — validation mandate

*Last updated: 2026-06-25*
