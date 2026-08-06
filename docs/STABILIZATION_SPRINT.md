# Stabilization Sprint — Phase 1 Production Readiness

**Started:** 2026-06-12  
**Scope:** Reliability, recoverability, testing, documentation — **no new trading features**  
**Bots:** DRISHTI, KAVACH, JAGRAN (+ SARANSH optional)

---

## Sprint objective

Make the existing Python trading ecosystem **reliable, stable, testable, recoverable, and production-ready** without changing strategy, entry/exit logic, or ATO behavior.

---

## Success criteria

| Criterion | Target | Status |
|-----------|--------|--------|
| Startup | Deterministic Start All; reconcile heals stale locks | **Done** |
| WebSocket | Stable NIFTY feed; no false failover on control frames / 429 | **Done** |
| Token | JWT-effective expiry gates feed; pause/resume uses correct state file | **Done** |
| Recovery | Failover + ATO pause flags survive DRISHTI restart | **Done** |
| Testing | pytest stabilization subset green; phase1_bot_check pass | **Done** |
| Docs | This file + handoff updated | **Done** |
| Operator UAT | Manual Telegram + Gate 5 walkthrough | **Deferred** — off-hours validation PASS 2026-06-25; market-hours 15-cycle pending |

---

## Operator testing (your turn)

Full checklist: **`NEW_CHAT_HANDOFF.md` §4**

Quick start:

```powershell
.venv\Scripts\python.exe scripts\stabilization_verify.py
Execution\Show Bot Status.bat
```

Then: Stop All → Start All cycle; DRISHTI NIFTY Status + Live Price; KAVACH pause/resume; Gate 5 per `GATE5_RUNBOOK.md`.

**Important:** Use `Execution\Start Bots\` and `Execution\Stop Bots\` only — not ad-hoc `python run_*.py`.

---

## Sprint status

**STAB-01…15: FIXED** (2026-06-12). Agent validation passed.  
**2026-06-25:** Off-hours full validation PASS (pytest, stabilization, lifecycle harness, MCX probe). Market-hours 15-cycle live NIFTY proof pending — `docs/RELIABILITY_TOMORROW_HANDOFF.md`.  
**2026-06-25 hotfix:** Windows cache-replace race in `data/nifty_ltp_cache.json` no longer tears down the DRISHTI feed task; see `INC-2026-023`.

---

## Issue register

Reporting format for each item:

### STAB-01 — UAT state-file split-brain (ATO pause)

| Field | Detail |
|-------|--------|
| **Issue** | DRISHTI feed failure called `pause_algo()` on `data/batman_state.json` while KAVACH UAT reads `data/uat/batman_state.json` |
| **Root cause** | Hard-coded default state path in `algo_control` / `feed_recovery` |
| **Affected modules** | `core/algo_control.py`, `core/feed_recovery.py`, `bat_telegram/bots/drishti/nifty_feed_integration.py` |
| **Risk** | **High** — ATO may not pause on feed failure in UAT |
| **Fix** | `default_state_path()` → `state_path(workspace_root())` (mode-aware) |
| **Testing** | `tests/test_algo_control.py`, `tests/test_feed_recovery.py`, UAT mode integration |
| **Result** | **Fixed 2026-06-12** |

### STAB-02 — KAVACH menu reads wrong pause state (UAT)

| Field | Detail |
|-------|--------|
| **Issue** | Resume / recovery buttons used `StateManager()` default path |
| **Root cause** | `_read_algo_pause_reason()` not mode-aware |
| **Affected modules** | `kavach-2.0/bat_telegram/bots/kavach2/bot.py` |
| **Risk** | **High** |
| **Fix** | Use `state_path(workspace_root())` |
| **Result** | **Fixed 2026-06-12** |

### STAB-03 — Failover state lost on DRISHTI restart

| Field | Detail |
|-------|--------|
| **Issue** | WS→REST session lock lived only in `app.bot_data` |
| **Root cause** | No disk persistence; Telegram polling restart rebuilds app |
| **Affected modules** | `core/nifty_ltp_failover.py` |
| **Risk** | **High** during feed outages |
| **Fix** | Persist to `batman_state.json` key `nifty_ltp_failover` |
| **Result** | **Fixed 2026-06-12** |

### STAB-04 — WebSocket Previous Close treated as error

| Field | Detail |
|-------|--------|
| **Issue** | Dhan v2 `Previous Close` frame caused reconnect loop |
| **Root cause** | Missing LTP key treated as fatal |
| **Affected modules** | `core/dhan_ws_tick.py`, `core/nifty_ltp_websocket_feed.py` |
| **Risk** | **High** |
| **Fix** | Skip non-LTP control frames |
| **Result** | **Fixed 2026-06-12** (prior session) |

### STAB-05 — WebSocket 429 reconnect storm

| Field | Detail |
|-------|--------|
| **Issue** | HTTP 429 incremented failures → failover → REST lock |
| **Root cause** | No WS rate-limit cooldown (REST had one) |
| **Affected modules** | `core/nifty_ltp_websocket_feed.py` |
| **Risk** | **High** |
| **Fix** | 429 cooldown; no failure increment |
| **Result** | **Fixed 2026-06-12** |

### STAB-06 — WS 429 triggers false stale failover

| Field | Detail |
|-------|--------|
| **Issue** | 30s cooldown exceeded 5s WS stale threshold |
| **Root cause** | Stale watchdog ignored `rate_limit_until` |
| **Affected modules** | `core/nifty_ltp_feed.py`, `core/nifty_ltp_websocket_feed.py` |
| **Risk** | **Medium–High** |
| **Fix** | Skip stale alerts during rate-limit cooldown; refresh `last_update_at` on WS 429 |
| **Result** | **Fixed 2026-06-12** |

### STAB-07 — Feed gating used save-age only, not JWT exp

| Field | Detail |
|-------|--------|
| **Issue** | Feed ran with Dhan-rejected JWT while `saved_at` still valid |
| **Root cause** | `is_expired()` vs `effective_expires_in_hours()` mismatch |
| **Affected modules** | `core/token_store.py`, `nifty_feed_integration.py` |
| **Risk** | **High** |
| **Fix** | `is_effectively_expired()` for feed gating |
| **Result** | **Fixed 2026-06-12** |

### STAB-08 — Startup lock / PID reuse failures

| Field | Detail |
|-------|--------|
| **Issue** | ORPHAN locks, wrong UAT lock path, PID reuse |
| **Root cause** | Plain PID locks; path mismatch in stop-all |
| **Affected modules** | `core/instance_lock.py`, `core/bot_lifecycle.py`, `core/bot_supervisor.py` |
| **Risk** | **High** |
| **Fix** | Tier 1+2 lifecycle hardening |
| **Result** | **Fixed 2026-06-12** (prior session) |

### STAB-09 — Auth errors retried / caused failover

| Field | Detail |
|-------|--------|
| **Issue** | HTTP 401 treated as connection error → retry storm + WS↔REST failover |
| **Root cause** | No `BrokerAuthError` mapping; hooks always failover |
| **Affected modules** | `core/nifty_ltp.py`, `core/nifty_ltp_feed.py`, `core/nifty_ltp_websocket_feed.py`, `nifty_feed_integration.py` |
| **Risk** | **High** |
| **Fix** | `is_auth_error()`, `on_auth_failure` hook — no retry, no failover |
| **Result** | **Fixed 2026-06-12** |

### STAB-10 — KAVACH cold-start without JWT

| Field | Detail |
|-------|--------|
| **Issue** | KAVACH started before DRISHTI saved JWT — no broker/ATO until manual restart |
| **Root cause** | `token_watch` skipped when broker was None |
| **Affected modules** | `core/token_watch.py`, `run_kavach2.py` |
| **Risk** | **High** |
| **Fix** | Lazy bootstrap via `on_token_ready` callback |
| **Result** | **Fixed 2026-06-12** |

### STAB-11 — Supervisor ignored LTP gate failure

| Field | Detail |
|-------|--------|
| **Issue** | Start All spawned KAVACH/JAGRAN even when NIFTY cache stale |
| **Root cause** | LTP gate logged WARN only |
| **Affected modules** | `core/bot_supervisor.py` |
| **Risk** | **Medium** |
| **Fix** | Abort start (return 1) when LTP gate fails during market session |
| **Result** | **Fixed 2026-06-12** |

### STAB-12 — health.json not authoritative for RUNNING

| Field | Detail |
|-------|--------|
| **Issue** | Process scan alone could miss RUNNING bots or miss stale heartbeats |
| **Root cause** | `classify_bot()` ignored `data/health/{bot}.json` |
| **Affected modules** | `core/bot_health.py`, `core/bot_process_status.py` |
| **Fix** | `health_confirms_running()` upgrades status; stale heartbeat warnings |
| **Result** | **Fixed 2026-06-12** |

### STAB-13 — Session REST lock with no same-day WS retry

| Field | Detail |
|-------|--------|
| **Issue** | After WS→REST failover, WebSocket never retried until next trading day |
| **Root cause** | `session_rest_lock_date` blocked WS without retry path |
| **Affected modules** | `core/nifty_ltp_failover.py`, `nifty_feed_integration.py` |
| **Fix** | `try_websocket_retry_after_rest()` every 15 min in feed recovery watchdog |
| **Result** | **Fixed 2026-06-12** |

### STAB-14 — Live Price opened parallel one-shot WS

| Field | Detail |
|-------|--------|
| **Issue** | Telegram Live Price could spawn extra WS while background feed active |
| **Root cause** | Handler always opened new connection |
| **Affected modules** | `nifty_feed_integration.py` |
| **Fix** | Prefer fresh cache when background WS/REST feed healthy |
| **Result** | **Fixed 2026-06-12** (prior session) |

### STAB-15 — Lock timeout without retry on state writes

| Field | Detail |
|-------|--------|
| **Issue** | Single lock attempt could fail under concurrent bot writes |
| **Root cause** | `exclusive_file_lock()` had no retry |
| **Affected modules** | `core/process_lock.py` |
| **Fix** | `retries=3` with backoff on `TimeoutError` |
| **Result** | **Fixed 2026-06-12** |

### STAB-16 — Windows cache replace race destabilized live feed task

| Field | Detail |
|-------|--------|
| **Issue** | `WinError 5` while replacing `data/nifty_ltp_cache.json` caused the DRISHTI feed task to exit; watchdog kept restarting it |
| **Root cause** | Cache writer used a short Windows rename retry window and raised on persistent local file-lock races |
| **Affected modules** | `core/nifty_ltp_feed.py` |
| **Risk** | **High** — local filesystem contention could masquerade as WebSocket instability and trigger stale-cache pauses in KAVACH |
| **Fix** | Extended Windows-safe replace retries and made cache writes non-fatal after repeated replace-lock failures |
| **Result** | **Fixed 2026-06-25** |

---

## Verification script

Agent-owned multi-cycle check:

```powershell
.venv\Scripts\python.exe scripts\stabilization_verify.py
```

Runs 3 cycles: `bot_status`, token audit, `phase1_bot_check`, cache + health probes, stabilization pytest subset.

**Off-hours (market closed):** cache/LTP checks skipped via `ltp_gate_skip_reason()`. Full lifecycle:

```powershell
.venv\Scripts\python.exe scripts\run_reliability_off_hours_suite.py --cycles 5
```

**Market hours:** 15-cycle harness + live feed validation — see `docs/RELIABILITY_MARKET_HOURS_DEFERRED.md`.

```powershell
.venv\Scripts\python.exe scripts\run_phase1_reliability_loop.py --cycles 15 --wait-seconds 180
.venv\Scripts\python.exe scripts\generate_reliability_engineering_report.py
```

---

## Testing discipline (mandatory per fix)

1. Implement minimal diff  
2. Targeted pytest  
3. Full pytest suite  
4. `scripts/audit_bot_tokens.py` + `scripts/phase1_bot_check.py`  
5. Read today's DRISHTI/KAVACH logs for ERROR  
6. Repeat startup cycle ≥2 when touching lifecycle  

**Do not mark resolved after a single successful run.**

---

## Read order for agents

1. `docs/STABILIZATION_SPRINT.md` (this file)  
2. `NEW_CHAT_HANDOFF.md`  
3. `docs/BOT_LIFECYCLE_ARCHITECTURE.md`  
4. `NIFTY_LTP_POLICY.md`  
5. `docs/BATMAN_FEED_OPERATOR_RUNBOOK.md`  
6. `TESTING_PROTOCOL.md`  
7. `Execution/PHASE1_ROBOT_LAUNCHER.md`  

---

## Architecture (unchanged)

Four independent OS processes; disk-only coordination. No strategy changes. DRISHTI owns NIFTY LTP; KAVACH/ATO consume cache only.

---

*Last updated: 2026-06-12 — sprint complete; operator UAT testing*
