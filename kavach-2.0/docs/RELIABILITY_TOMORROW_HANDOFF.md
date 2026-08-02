# Reliability — Tomorrow Handoff (2026-06-26)

**From:** 2026-06-25 off-hours validation session (closed).  
**Goal:** Complete **market-hours** reliability sign-off; optional UAT E2E + Gate 5.

---

## What is already green (do not re-do unless regression)

- Off-hours lifecycle: **5/5** + **2/2** cycles PASS
- Full pytest suite PASS (with expected skips when bots stopped)
- Stabilization verify, token audit, incident fixes, MCX probe
- Code: telegram runtime/delivery, cache replace hardening, supervisor LTP gate, off-hours gate skip

**Artifacts:**

| File | Cycles |
|------|--------|
| `data/analytics/reliability/phase1_reliability_20260625_155803.json` | 5/5 off-hours |
| `data/analytics/reliability/phase1_reliability_20260625_165603.json` | 2/2 off-hours |

---

## Tomorrow morning — agent sequence (IST market day)

### Phase A — Preflight (09:00–09:14 optional)

```powershell
cd "H:\RK Data\Algo Trading Parent\DEV Batman Algo"
.venv\Scripts\python.exe scripts\audit_bot_tokens.py
.venv\Scripts\python.exe scripts\bot_status.py all
```

Bots may be **STOPPED** overnight — that is correct.

### Phase B — Start feed (≥09:15 IST)

```powershell
Execution\Start Bots\Phase 1 Start All Robots.bat
```

Or agent: `scripts\phase1_start_all.py`

Wait until DRISHTI writes fresh cache:

```powershell
.venv\Scripts\python.exe scripts\phase1_bot_check.py
```

Check `data\nifty_ltp_cache.json`: `feed_healthy=true`, age &lt; 90s, source `dhan_websocket` or `dhan_rest`.

### Phase C — 15-cycle live harness (main sign-off)

```powershell
.venv\Scripts\python.exe scripts\run_phase1_reliability_loop.py --cycles 15 --wait-seconds 180
```

**Pass criteria:** every cycle PASS; `price_flow_mode: live_session_feed_healthy`.

On FAIL → diagnose logs → fix → retry (max 4 loops). See `batman-debug-robot` rule.

### Phase D — Report

```powershell
.venv\Scripts\python.exe scripts\generate_reliability_engineering_report.py
```

Update `SESSION_CAPTURE_LOG.md` row: market-hours deferred **COMPLETE**.

### Phase E — UAT E2E (if operator wants Register/ATO path)

```powershell
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

Full autonomous loop: `UAT_E2E_AGENT.md`.

### Phase F — Gate 5 (optional, same day if time)

Follow `GATE5_RUNBOOK.md` — mock ATO breach/retrace on shadow book.

### Phase G — Shutdown

```powershell
Execution\Stop Bots\Phase 1 Stop All Robots.bat
```

Confirm: `scripts\bot_status.py all` → all STOPPED.

---

## Log paths (today = 2026-06-26)

```
logs/runtime/2026-06/2026-06-26/
  logs/all.log
  drishti/logs/all.log
  drishti/errors/all_errors.log
  kavach/logs/all.log
  kavach/errors/all_errors.log
  jagran/logs/all.log
```

UAT mode may mirror under `logs_uat/runtime/...` — check `config/batman_mode.json`.

---

## UAT fixture note

`uat/deployed_positions/positions.json` expiry set to **2026-06-30** (rolled from expired 2026-06-23). Shadow book may show **5 rows** if virtual ATO fill exists in ledger — normal mid-session.

---

## If market closed / holiday tomorrow

Run off-hours suite only:

```powershell
.venv\Scripts\python.exe scripts\run_reliability_off_hours_suite.py --cycles 5
.venv\Scripts\python.exe scripts\mcx_silver_probe.py --contract jul
```

Defer Phase C until next NSE session.

---

## Copy-paste for new Cursor chat

```
Read NEW_CHAT_HANDOFF.md and docs/RELIABILITY_TOMORROW_HANDOFF.md.
Execute market-hours reliability sign-off (15-cycle harness).
Then UAT E2E if green. Agent verifies everything — I only give instructions.
```
