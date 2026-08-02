# Bot lifecycle architecture — laptop today, VPS tomorrow

Last updated: 2026-06-12  
Status: **Tier 1 complete** · **Tier 2 supervisor MVP live** (default Start All path)

---

## Problem summary

Start/stop failures on the dev laptop come from **infrastructure fragility**, not trading logic:

| Failure mode | Root cause |
|--------------|------------|
| Start All aborts | Stop-all could not prove STOPPED (stale lock, wrong lock path, PID reuse) |
| Bot “won’t start” | Lock file says PID alive; Windows reused that PID for another process |
| Bot “won’t stop” | CMD window closed with **X** → Python orphan; lock out of sync |
| Duplicate bots | Agent terminal + `.bat` both started same bot |
| Mode mismatch | UAT lock at `data/uat/kavach.lock` but stop script looked at `data/kavach.lock` |

The current model stacks **four weak signals** and treats disagreement as hard failure:

1. WMI command-line scan (`find_pids_by_commandline`)
2. Plain-text PID lock file (`data/.../kavach.lock`)
3. Auxiliary `.pidlock` (atomic create)
4. Optional `health.json` heartbeat (underused for lifecycle)

On Windows, **PID alone is not identity**. After a crash, the same numeric PID can belong to Chrome, Cursor, or `svchost` — blocking start for a bot that is not running.

---

## Design principles (locked for VPS)

1. **One source of truth per question**
   - *Is the bot running?* → fresh `health.json` + command-line PID match (not lock PID alone)
   - *May I start?* → supervisor or start script decides; never operator guesswork
   - *Is it safe to trade?* → KAVACH state + DRISHTI LTP cache (unchanged)

2. **Supervisor owns lifecycle** — bots do not self-orchestrate bulk start/stop via `.bat` chains on production.

3. **Fail open on stale locks, fail closed on live duplicates** — remove provably stale locks automatically; refuse start only when a real `run_*.py` process exists.

4. **Graceful shutdown** — SIGTERM → drain Telegram → release lock (VPS/Linux). No dependence on `taskkill` for normal ops.

5. **Four processes stay four processes** — DRISHTI / KAVACH / JAGRAN / SARANSH remain independent (CONTEXT §23). We change *how they are managed*, not merge them.

---

## Three-tier roadmap

### Tier 1 — Hardening (laptop) ✅ complete

| Item | Status |
|------|--------|
| Mode-aware lock paths (`bot_lock_path`) | Done |
| PID reuse → GHOST_LOCK + auto-remove | Done |
| Auto-heal ghost locks in stop-all / start-all | Done |
| `scripts/reconcile_bots.py` one-shot heal | Done |
| `bot_status.py` auto-heals before display | Done |
| Structured lock JSON (`core/instance_lock.py`) | Done |
| `single_instance.py` validates cmdline, not OpenProcess only | Done |

### Tier 2 — Python supervisor ✅ MVP (2026-06-12)

| Item | Status |
|------|--------|
| `core/bot_supervisor.py` + `scripts/bot_supervisor.py` | Done |
| `Phase 1 Start All` uses supervisor by default | Done |
| `Supervisor Start All.bat` / `Supervisor Stop All.bat` | Done |
| `--legacy-bats` fallback on phase1_start_all | Done |

**Operator command when anything feels stuck:**

```bat
.venv\Scripts\python.exe scripts\reconcile_bots.py
```

Then `Show Bot Status.bat` — all bots should show STOPPED or RUNNING, never ORPHAN/GHOST.

**Future Tier 2 enhancements:** long-lived supervisor daemon, crash auto-restart, `health.json` as primary RUNNING signal (BL-07).

---

### Tier 3 — VPS production (Linux + systemd)

**Goal:** 100% unattended uptime; auto-restart; no GUI.

```
systemd target: batman-phase1.target
  ├── batman-drishti.service   (Restart=always, WatchdogSec=120)
  ├── batman-kavach.service    (After=drishti, Wants=drishti)
  ├── batman-jagran.service
  └── batman-saransh.service   (optional)
```

| Topic | Decision |
|-------|----------|
| OS | Linux VPS (Ubuntu 22.04+); avoid Windows Server for prod bots |
| Start order | systemd `After=` + `ExecStartPre=` LTP gate script |
| Logs | journald + existing `logs_prod/runtime/` layout |
| Deploy | git pull + `systemctl restart batman-kavach` per bot |
| Health | `health.json` + systemd watchdog; JAGRAN alert if stale > 2 min |
| Locks | Same JSON lock; Linux PIDs less chaotic but same validation rules |

**Out of scope for Tier 3:** merging bots into `main.py` single process (explicitly deferred in CONTEXT).

---

## What operators should do today

1. **Always** start/stop via `Execution\Start Bots\` / `Stop Bots\` — never CMD **X**.
2. After agent debug in Cursor terminal → run **Stop All** or `reconcile_bots.py`.
3. If Start All fails → run `reconcile_bots.py`, then Start All again (no manual lock deletion).
4. Confirm with **Show Bot Status** before trusting state.

---

## Implementation tracker

| ID | Task | Tier | Owner |
|----|------|------|-------|
| BL-01 | `bot_lock_path` + PID reuse fix | 1 | Done 2026-06-12 |
| BL-02 | `reconcile_bots.py` | 1 | Done 2026-06-12 |
| BL-03 | Auto-heal in status/start/stop | 1 | Done 2026-06-12 |
| BL-04 | Structured `instance_lock.py` | 1 | Done 2026-06-12 |
| BL-05 | `bot_supervisor.py` MVP | 2 | Done 2026-06-12 |
| BL-06 | systemd unit files + VPS runbook | 3 | **Done** — `vps/systemd/*`, `docs/AWS_ALWAYS_ON_DEPLOY.md` |
| BL-07 | Deprecate WMI-only PID checks in favor of health.json | 2 | With BL-05 |

---

## Related docs

- `NEW_CHAT_HANDOFF.md` — session bridge; read first in new chat
- `Execution/PHASE1_ROBOT_LAUNCHER.md` — current operator guide
- `CONTEXT.md` §3.1 + §3.3 — four-process lock + lifecycle tiers
- `PHASE1_OPEN_QUESTIONS.md` PQ-18 — VPS auto-restart (superseded by this doc)
- `ROBOT_DEBUG_PROTOCOL.md` — agent diagnose loop

---

## Session 2026-06-12 — code changes (reference)

### Files touched

| File | Change |
|------|--------|
| `core/bot_process_status.py` | `bot_lock_path()`, `_lock_pid_owns_runner()`, PID reuse → GHOST_LOCK |
| `core/bot_launcher.py` | Mode-aware locks in pre-start / force-stop |
| `scripts/phase1_stop_all.py` | `bot_lock_path` + auto-heal GHOST_LOCK in `_all_stopped` |
| `scripts/phase1_start_all.py` | Step 0 reconcile before stop-all |
| `scripts/reconcile_bots.py` | **New** — one-shot heal all bots |
| `scripts/bot_status.py` | Auto-heal ghost locks by default |
| `scripts/diagnose_robot.py` | Pass `runner_marker` to `remove_stale_lock` |
| `Execution/Start Bots/Reconcile Bots.bat` | **New** operator launcher |
| `tests/test_bot_process_status.py` | Recycled PID test case |

### UAT lock paths (mode = uat)

| Bot | Lock file |
|-----|-----------|
| KAVACH | `data/uat/kavach.lock` |
| SARANSH | `data/uat/saransh.lock` |
| DRISHTI | `data/drishti.lock` |
| JAGRAN | `data/jagran.lock` |
