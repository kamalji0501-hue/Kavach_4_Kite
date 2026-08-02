# Batman v3 - Project Context and Final Master Record

Last updated: 2026-07-15 (§26 Quick Tune coded + Chromebook Linux DEV — resume NEW_CHAT_HANDOFF.md)
Primary owner: Rahul
Execution model: **Phase 1 = four independent OS processes** (DRISHTI → KAVACH → JAGRAN → SARANSH optional), Telegram-first control; `main.py` five-bot orchestrator is **not** Phase 1 laptop runtime

> **New Cursor chat:** read **`NEW_CHAT_HANDOFF.md`** first (session paused **2026-07-15 night** — Quick Tune coded).  
> **Prior UAT fast path:** §25 · **This resume:** §26  
> **Fast UAT (daily book change):** `FAST_UAT_PROMPT.md` · `scripts/quick_uat_positions_gate.py` · **no bot restart**  
> **Full UAT (code change / first boot):** `UAT_CHAT_POSITIONS.md` · `UAT_E2E_AGENT.md` · `scripts/run_uat_e2e_verification.py`  
> **Stabilization tracker:** `docs/STABILIZATION_SPRINT.md` · **Verify:** `scripts/stabilization_verify.py`  
> **Operator runbook:** `docs/BATMAN_FEED_OPERATOR_RUNBOOK.md` · **Policy:** `NIFTY_LTP_POLICY.md`  
> **Resume SARANSH/Gate 5:** §24 · `SARANSH_IMPLEMENTATION_STATUS.md` · `GATE5_RUNBOOK.md`  
> **Architecture:** §23 independence (no merge until explicit override)  
> **NIFTY LTP (2026-06-12):** WebSocket default stable; runtime WS↔REST failover persisted; same-day WS retry; auth fast-fail; JWT-effective expiry gating.  
> **Phase 1 scope (locked 2026-06-05):** DRISHTI, KAVACH, JAGRAN, **SARANSH** (4 bots). **UAT primary**. Gate 5: **all 4 RUNNING**.

## 1. Purpose

Batman v3 is a Telegram-controlled NIFTY options automation platform designed to run continuously, preserve state safely, and keep operations observable through logs, ledgers, and incident notifications.

This file is the authoritative current-state snapshot for final project closure.

## 2. Current Scope Lock (Active)

### Phase 1 rollout (2026-05-29 — authoritative for current work)

Active Telegram bots:
- DRISHTI
- KAVACH
- JAGRAN
- SARANSH (4th — optional startup if token missing; reporting)

Out-of-scope for Phase 1 (comment out / disable, do not delete):
- LAKSHMI
- SANCHALAK
- RATRIPAL, PRABHAT MUKTI, profit trailing, overnight hedge
- Emergency exit **module** (automated watchdog) — disabled; KAVACH `/exit` **removed** (use Pause/Resume + Batman Complete)

Full operator requirements: `PHASE1_REQUIREMENTS.md`  
Unresolved Phase 1 questions only: `PHASE1_OPEN_QUESTIONS.md`  
Dhan API reference: `DHAN_API_CONTEXT.md` · LTP policy: `NIFTY_LTP_POLICY.md` · Logs: `LOGGING_LAYOUT.md` · Debug: `ROBOT_DEBUG_PROTOCOL.md` · Folder cleanup: `FOLDER_MAINTENANCE.md`

### Earlier scope lock (2026-05-18 — superseded for bot count)

Previously active: DRISHTI, KAVACH, JAGRAN, SANCHALAK, SARANSH. SANCHALAK and SARANSH deferred to a later phase.

## 3. Runtime Architecture (Locked)

### Phase 1 laptop (authoritative today)

- **Three separate Python processes** — one per bot:
  - `run_drishti.py` — JWT, NIFTY REST poll → `data/nifty_ltp_cache.json`, health
  - `run_kavach.py` — Register, ATO, deployment state, UAT ShadowBroker
  - `run_jagran.py` — critical incidents + operator UI
- **Do not merge** DRISHTI and KAVACH into one process (operator lock **§23**). Independence is intentional: separate windows, separate logs, separate restart, separate failure domains.
- Bots coordinate **only via disk artifacts** (not shared in-memory state):
  - `data/access_token.json` (DRISHTI writes → KAVACH reads)
  - `data/nifty_ltp_cache.json` (DRISHTI writes → KAVACH/ATO reads)
  - `data/{mode}/batman_state.json`, deployments, shadow ledger (KAVACH/UAT)
- Shared **library** code in `core/` (broker, state, event_bus, launcher guards) — imported per process, not a single fused runtime.
- Main runtime bot code lives in `bat_telegram/bots/`.
- Legacy `bot/` folder remains retired reference only.

### Future / VPS (`main.py` — out of Phase 1 scope)

- Historical design: single asyncio process launching multiple Telegram tasks + `AlgoScheduler`.
- **Not** the operator path on dev laptop. Phase 1 uses `Execution/Start Bots/` only.
- Design assets: `telegram/design/architecture.md` (legacy single-process diagram).

### 3.1 Phase 1 laptop bots — launcher lifecycle (locked 2026-06-02)

**Architectural principle:** DRISHTI, KAVACH, and JAGRAN are **not** started or stopped by closing a CMD window (X), and the operator does **not** use ad-hoc `python run_*.py` from a shell. The only approved operator path is the **Execution** `.bat` launchers. Cursor/agent may use the matching `scripts/stop_*.py`, `scripts/bot_status.py`, and `scripts/ensure_bot_stopped.py` for automation.

| Action | Operator path | Verification |
|--------|---------------|--------------|
| **Start all** (Phase 1) | `Execution\Start Bots\Phase 1 Start All Robots.bat` | Stop-first; 3 windows; **2 min** verify RUNNING; logs `launchers/start_all/`; 5s auto-close on success |
| **Stop all** (Phase 1) | `Execution\Stop Bots\Phase 1 Stop All Robots.bat` | **5 retries**; verify STOPPED; logs `launchers/stop_all/`; error **popup** on failure; 5s auto-close on success |
| **Reconcile** (stuck locks) | `Execution\Start Bots\Reconcile Bots.bat` | Auto-heal GHOST_LOCK / stale UAT locks; run before Start All if abort |
| Start one | `Execution\Start Bots\start <Bot>.bat` | Step 2 runs `ensure_bot_stopped` — **start aborts** if any `run_*.py` process remains |
| Stop one | `Execution\Stop Bots\stop <Bot>.bat` | Post-stop `ensure_bot_stopped --after-stop` — window stays open on failure |
| Status | `Execution\Start Bots\Show Bot Status.bat` (copy in Stop Bots too) | Shows RUNNING / STOPPED / ORPHAN / GHOST_LOCK per bot |
| Diagnose | `scripts\diagnose_robot.py <bot>` | Same process detection as stop/status (shared `core/bot_process_status.py`) |

Full launcher guide: **`Execution/PHASE1_ROBOT_LAUNCHER.md`**

**Do not:** click X on the “Bot - Running” window (orphan Python may keep trading/Telegram alive).  
**Do not:** assume stopped because the window disappeared — run **Show Bot Status** or stop `.bat` again.

Implementation map (all three Phase 1 bots):

- `core/bot_process_status.py` — WMI command-line PID detection + lock file classification
- `core/bot_launcher.py` — pre-start cleanup, `BATMAN_LAUNCHED_VIA_BAT` guard, blocked-start messages
- `scripts/ensure_bot_stopped.py` — preflight (start) and post-stop verification
- `Execution\Start Bots\_preflight_start.bat` — called by every start `.bat` after silent stop
- `Execution\Stop Bots\_verify_stopped.bat` — called by every stop `.bat` after `stop_*.py`
- `run_drishti.py` / `run_kavach.py` / `run_jagran.py` — `bootstrap_exclusive_bot()` (scan tray → kill **same bot only** → single-instance lock)
- `core/bot_instance_guard.py` — process-tray snapshot before every start
- `core/deployment_lock.py` — global lock for Register confirm / Batman Complete / ATO entry (KAVACH process)
- `core/startup_gates.py` — DRISHTI RUNNING + LTP freshness before KAVACH in `phase1_start_all.py`
- `scripts/phase1_post_start_verify.py` · `scripts/run_daily_health.py` — post-start and daily health loops
- `core/market_data_guard.py` — cache-first position enrich; no ×50 option chain; 2s debounce/throttle (§23.5)
- `core/nifty_ltp_feed.py` — `cache_consumer_status()` heartbeat fields in `nifty_ltp_cache.json` (§23.4 #1)
- `core/bot_health.py` — per-bot `data/runtime/{bot}/health.json` every 30s (§23.4 #2)
- `core/dhan_rest_quote.py` — REST quote client with 2s cache (exact strikes only)
- `core/session_bundle.py` — UAT session persist on register confirm

Recovery: if start is blocked, run **Reconcile Bots** or the matching **stop** `.bat`, confirm **STOPPED** in Show Bot Status, then start once. Optional: `start <Bot>.bat force` re-runs stop inside preflight. **Start All** reconciles locks first, then stop-all, then sequential DRISHTI → KAVACH → JAGRAN with `force`.

**Lifecycle architecture (2026-06-12):** Start/stop fragility on Windows (PID reuse, stale locks, UAT path mismatch) is addressed in **Tier 1** hardening; **Tier 2** supervisor default for Start All; **Tier 3** VPS systemd planned before production. Authoritative docs: **`docs/BOT_LIFECYCLE_ARCHITECTURE.md`**, **`docs/STABILIZATION_SPRINT.md`**. Handoff: **`NEW_CHAT_HANDOFF.md`**.

**Stabilization sprint (2026-06-12):** Reliability hardening STAB-01…15 complete — WebSocket stability, auth fast-fail, UAT state-path fix, failover persistence, `health.json` RUNNING confirmation, same-day WS retry after REST, lock retries, KAVACH lazy JWT bootstrap, supervisor LTP gate. Agent verify: `scripts/stabilization_verify.py`. **No trading/ATO logic changes.**

### 3.2 Incident tracker — domain error files (locked 2026-06-02)

Errors are recorded into **six domain folders** under `data/analytics/incidents/by_domain/`:

| Domain | Captures |
|--------|----------|
| drishti / kavach / jagran | Standalone bots (logging ERROR+) |
| main | `main.py` orchestrator when five-bot runtime is used |
| start_all / stop_all | Phase 1 bulk launchers |

Each domain: daily CSV + errors log; **operator_status** `open`/`closed`; `open_registry.json` survives restarts.  
**Repeat ≥ 3** → JAGRAN `incident_repeat_escalation`.  
Dashboard: `scripts/incident_report.py` · `scripts/incident_dashboard.py` → weekly XLSX · `Execution/Incident Dashboard.bat`.  
Close open items: `scripts/incident_close.py`. Simulator + `main.py` → **main** domain.  
Full spec: **`INCIDENT_TRACKER.md`**

### 3.3 Bot lifecycle architecture — three tiers (locked direction 2026-06-12)

| Tier | Scope | Status |
|------|--------|--------|
| 1 | Laptop hardening: structured locks, reconcile, PID reuse auto-heal | **Done** |
| 2 | `bot_supervisor.py` — Start All spawns `run_*.py` directly (default) | **Done (MVP)** |
| 3 | Linux VPS + systemd auto-restart | Before prod cutover |

Operator when stuck: `Execution\Start Bots\Reconcile Bots.bat` → Show Bot Status → Start All.

Implementation: `core/instance_lock.py`, `core/bot_lifecycle.py`, `core/bot_supervisor.py`, `scripts/bot_supervisor.py`. Legacy `.bat` per-bot start: `phase1_start_all.py --legacy-bats`.

## 4. Major Design and Control Locks

The following are locked and already reflected in code unless explicitly marked otherwise:

1. Startup must fail if JAGRAN token environment is missing/invalid.
2. Pause behavior is read-only:
   - Status/read commands allowed.
   - Action/trading commands blocked.
3. Canonical command names are used; old aliases removed from active command surface.
4. SANCHALAK control authority is higher than downstream trading bot actions.
5. Broker-level mock-mode guard blocks real order placement.
6. SARANSH summary model is dual-delivery (Telegram plus file) with incident escalation on channel failure.
7. Active-scope simulator must mirror control-plane semantics (pause, mode, and command behavior).

## 5. Implementation Status by Domain

### 5.1 Completed and coded

- ATO module core behavior (entry/retrace/startup scan/side gating).
- KAVACH deployment and command flows (including break-even and ATO controls).
- DRISHTI token handling, health flow, and fleet visibility surface.
- SANCHALAK runtime command surface and overlap protection.
- SARANSH summary flow and incident-linked delivery behavior.
- JAGRAN incident routing foundations with dedup/recovery transitions.
- Runtime logging architecture (text-first, IST millis, time-window files).
- Incident ledger pipelines and workbook export flow.
- Simulator interlinks for active five-bot scope.
- Technical implementation playbook and governance framework artifacts.
- **2026-06-05 independence pack (§23):** NIFTY cache heartbeat, per-bot `health.json`, JAGRAN severity routing, ATO idempotency keys, cache-first `market_data_guard`.
- **2026-06-05 infra hardening (§23.3):** single-instance reclaim, deployment lock, sequential start gates, post-start verify, daily health, REST quote throttle, session bundle, protect-symbol derive on sync.

### 5.2 Coded but still validation-pending

- SANCHALAK live command walk-through on real chat wiring.
- End-to-end simulator command matrix execution with pass/fail evidence capture.
- Live broker smoke test against actual Dhan token/session.
- Full VPS transition validation (startup/restart/permissions/artifact checks).
- JAGRAN runtime fatal gating and routed recovery path validation in fully configured environment.

### 5.3 Deferred by scope lock

- LAKSHMI operational return.
- RATRIPAL follow-up validation/enhancements.
- PRABHAT MUKTI continuation.

## 6. ATO Analytics State (Important)

Recent hardening done in modules/ato_protection.py:
- Duplicate-tail guard on telemetry append.
- Duplicate-tail guard on consolidated ledger append.
- Deterministic XLSX writer engine selection via openpyxl.
- **ATO idempotency keys** — `YYYY-MM-DD:CE|PE:BUY:symbol` via `core/ato_idempotency.py` (no duplicate protect BUY on retry).
- **Stale NIFTY cache policy** — consecutive cache failures → JAGRAN `MODULE_ERROR` + auto-pause (`algo.pause_reason=nifty_ltp_cache_stale`); KAVACH does **not** poll Dhan for spot (reads `nifty_ltp_cache.json` only).

Current evidence snapshot on this machine:
- ATO XLSX snapshot files found: 0
- Interpretation: no runtime cycle has produced workbook artifacts yet in current data state, or export path has not been exercised in live-like flow.
- Required closure evidence: execute at least one full ATO cycle in runtime path and verify XLSX snapshot creation under data/analytics/ato/snapshots.

## 7. Quality Gate Evidence (Latest)

Latest executed verification (2026-06-05 independence + market guard pass):
- pytest: **PASS** — `test_market_data_guard.py`, `test_uat_position_enrich.py`, `test_independence_features.py`, `TestATOProtection` (11), deployment/startup/bot-instance guard suites
- Targeted independence + enrich: **13/13** pass
- ATO protection unit tests: **11/11** pass
- ruff: PASS on `core/market_data_guard.py`, `core/uat_position_enrich.py`, `tests/test_market_data_guard.py` (pre-existing import-order note in `ato_protection.py` only)

Prior baseline (2026-05-30): pytest 189, mypy core/modules PASS, ruff/black on reliability files PASS.

## 7.1 Reliability Hardening (2026-05-30 — no strategy logic changes)

Multi-process Phase 1 laptop fixes:
- `StateManager.refresh_algo_flags_from_disk()` — KAVACH ATO sees DRISHTI auto-pause
- File lock on state save (`core/process_lock.py`)
- KAVACH `post_init` binds asyncio loop for EventBus Telegram pushes
- `core/token_watch.py` — KAVACH hot-reloads JWT when DRISHTI saves token
- Broker `_snapshot_tsl()` — thread-safe Tradehull access during hot-reload
- ATO consecutive LTP failure alerting; managed-qty check only when `deployment.confirmed`
- Module max-restart publishes `MODULE_ERROR`; CSV append lock for ATO analytics

Pass 2 (same session):
- DRISHTI per-chat token wait state (`user_data`) — safe with `concurrent_updates`
- TYPE-1 token reminder dedup (one fire per scheduled slot per day)
- Token save shows broker reconnect notice when hot-reload fails
- `TokenStore` threaded + file-locked reads/writes
- `core/single_instance.py` shared by DRISHTI/KAVACH/JAGRAN launchers
- Repo-wide ruff/black cleanup (all ruff checks pass; 189 pytest pass)

## 7.2 Infrastructure + independence hardening (2026-06-05)

**Operator lock:** DRISHTI, KAVACH, JAGRAN stay **three separate OS processes** — merge rejected (§23.2).

| Layer | Module / script | Purpose |
|-------|-----------------|--------|
| Single instance | `core/bot_instance_guard.py`, `core/single_instance.py` | Scan tray; kill **same bot only**; reclaim lock on conflict |
| Deployment lock | `core/deployment_lock.py` | Register confirm, Batman Complete, ATO `_place_*` — no overlapping writes |
| Start gates | `core/startup_gates.py`, `scripts/phase1_start_all.py` | DRISHTI RUNNING + fresh LTP before KAVACH; then JAGRAN |
| Post-start | `scripts/phase1_post_start_verify.py` | RUNNING + token + cache checks after Start All |
| Daily health | `scripts/run_daily_health.py` | Scheduled bot/cache/JWT sanity |
| REST throttle | `core/dhan_rest_quote.py` | 2s cached quotes; exact securityIds only |
| Session bundle | `core/session_bundle.py` | UAT register → persist deployment + positions snapshot |
| Protect derive | `bat_telegram/bots/kavach/bot.py` | `_derive_ato_protect_fields` on position sync |
| Cache heartbeat | `core/nifty_ltp_feed.py` | `ready_for_consumers`, `cache_age_seconds`, `collector` in cache JSON |
| Bot health | `core/bot_health.py` | `data/runtime/{drishti,kavach,jagran}/health.json` every 30s |
| Severity | `core/incident_severity.py` | DRISHTI feed=warning; KAVACH order fail=critical |
| ATO idempotency | `core/ato_idempotency.py` | Dedup protect BUY keys per day/side/symbol |
| **Market guard** | `core/market_data_guard.py` | Fixture-first enrich; disable ×50 chain; 2s debounce/throttle (§23.5) |

**2026-06-05 log audit fixes (UAT):**
- KAVACH Positions **MarkdownV2** escape errors (~68 handler failures before ~13:55) — fixed in `kavach/bot.py`
- **CE protect symbol race** during Batman Complete — fixed in ATO + sync path
- JAGRAN **missing error handler** — `add_error_handler` wired in `run_jagran.py`

**Pending operator decision:** Canary register dry-run (§23.7) — always / flag / skip.

**After code deploy:** restart bots via `Execution\Start Bots\` so `health.json` + market guard are live.

## 8. Governance and Documentation State

Synced artifacts:
- IMPLEMENTATION_TRACKER.md
- IMPLEMENTATION_TRACKER.csv
- SESSION_CAPTURE_LOG.md
- reference/DECISION_REGISTER.md
- reference/DISCUSSION_CAPTURE.md
- reference/TECHNICAL_IMPLEMENTATION_PLAYBOOK.md

Governance contract remains active:
- Every meaningful session must update tracker and session log.
- Design/code drift must be downgraded immediately when detected.

Confidentiality hardening status:
- First-party repository examples were sanitized to placeholder-only token/JWT values.
- No first-party file should contain real credentials, real JWT payloads, or token-formatted samples.
- Developers must populate secrets only in ignored runtime files (for example `token.env`), never in committed files.

## 9. Open Risk Register (Condensed)

From OPEN_QUESTIONS.md, primary unresolved operational risks before full production confidence:
- Full live broker smoke coverage not yet completed.
- Dry-run mode not implemented.
- Emergency market-order slippage controls not implemented.
- Condor structural validation guard still recommended.
- Unattended service-restart policy still design-pending.

These do not block code completeness for active scope, but they affect production risk posture.

## 10. Final Closure Criteria

Project can be declared operationally closed when all conditions below are true:

1. Active five-bot command walkthrough is validated with evidence.
2. End-to-end simulator scenario checklist is fully executed and logged.
3. Live broker smoke checklist is executed with safe test positions.
4. JAGRAN fatal startup + recovery routing behavior is proven in configured environment.
5. At least one runtime ATO cycle produces both CSV and XLSX analytics snapshot artifacts.
6. VPS smoke run report is captured as PASS/WARN/FAIL and reviewed.

## 11. Recommended Immediate Close-out Sequence

1. Complete simulator checklist and log evidence.
2. Run live broker smoke and log outcomes.
3. Trigger one controlled ATO cycle to verify XLSX snapshot generation.
4. Run Windows VPS smoke script with full env placeholders set.
5. Mark corresponding OPS_VALIDATION_PENDING tracker rows as CODED when evidence is complete.

## 12. If Project Is Being Concluded Today

Use this final statement:

- Codebase status: Active-scope implementation is complete and quality-gated.
- Operational status: Validation evidence collection remains for full production closure.
- Handoff artifacts: Context, tracker, decision log, discussion log, and technical playbook are in place.
- Re-entry method: Start with this CONTEXT.md, then execute the close-out sequence in Section 11.

## 13. File Ownership Shortcuts

- Runtime entrypoint: main.py
- Broker runtime controls: core/broker.py
- ATO logic and analytics: modules/ato_protection.py
- Global control interlocks: bat_telegram/control.py
- SANCHALAK bot: bat_telegram/bots/sanchalak/bot.py
- KAVACH bot: bat_telegram/bots/kavach/bot.py
- DRISHTI bot: bat_telegram/bots/drishti/bot.py
- SARANSH bot: bat_telegram/bots/saransh/bot.py
- Incident routing: bat_telegram/incident_publisher.py
- Simulator app: simulator/app.py
- Master tracker: IMPLEMENTATION_TRACKER.md
- Session audit log: SESSION_CAPTURE_LOG.md
- Technical methodology: reference/TECHNICAL_IMPLEMENTATION_PLAYBOOK.md
- Project size / LOC snapshot: `scripts/project_stats.py` (documented in §19)

## 14. Non-Negotiable Invariants

1. JAGRAN startup gate stays mandatory.
2. Pause means read-only, not silent/no-response.
3. Mock mode must never allow real broker order placement.
4. Canonical command contract remains stable unless intentionally versioned.
5. Tracker/session continuity process is mandatory for every meaningful session.
6. **Phase 1 bots stay separate processes** — never merge DRISHTI+KAVACH (or any Phase 1 pair) into one Python process without an explicit operator version bump (§23).
7. **KAVACH reads DRISHTI output from disk only** — no cross-process calls; NIFTY spot from `nifty_ltp_cache.json`; position enrich is fixture-first with `market_data_guard` (§23.5); Tradehull ×50 option chain fallback stays **off** unless explicitly opted in.

## 15. Phase 1 Handoff (2026-05-30 — session close, resume Saturday)

**Next session:** **Saturday 2026-05-30** — Rahul + AI connect together; start **all bots** + run **simulator** alongside Telegram.  
**Monday 2026-06-01:** **Gate 5** simulated ATO (mock) — see **`GATE5_RUNBOOK.md`**.  
**VPS / live orders:** ~**15 days** minimum; laptop stays **mock** until then.

### Operator decisions (locked tonight)

| Topic | Decision |
|-------|----------|
| Order mode | **Mock only** (not live) |
| Deployment | **Batman Complete** → verified cleanup → **fresh /register** |
| Registration | Full **4-leg** iron condor (both sides) |
| LTP feed intervals | **Operator chooses** in DRISHTI **LTP Feed Setup** (poll + stale) — do not hardcode for prod |
| Stop script auto-close | **5 seconds** on success; window stays open on error |
| Stop-all shortcut | **Out of scope** |
| ATO qty | From **managed BUY qty** (flexible leg ratios OK) |
| VPS timeline | ~**15 days** before production VPS + live mode |

### Architecture (locked)

| Layer | Owner | Role |
|-------|--------|------|
| Sense | DRISHTI | **Only** NIFTY LTP collector → `data/nifty_ltp_cache.json` (`NIFTY_LTP_POLICY.md`) |
| Decide | KAVACH/ATO | Read cache only — never Dhan for spot |
| Alert | JAGRAN | Stale feed, fetch failures, auto-pause |
| WebSocket | DRISHTI | **Health test only** (`Nifty LTP (WebSocket)` button) — not ATO hot path |

Auto-pause on bad feed; **manual Resume** on KAVACH (no auto-resume).

### Code completed since last handoff (2026-05-29 → 2026-05-30)

| Area | Status |
|------|--------|
| REST NIFTY feed module + DRISHTI setup UI | ✅ |
| Auto-pause ATO + JAGRAN on stale/fetch failures | ✅ |
| ATO wired in **`run_kavach.py`** standalone | ✅ |
| Register wizard — **no 1:2 ratio block**; **qty→lots** (÷65) fix | ✅ |
| Batman Complete — **verified cleanup** confirmation | ✅ |
| Simulator — side-scoped register + lots + cleanup parity | ✅ |
| DRISHTI UI — Fleet removed; **Deactivate Token**; **Nifty LTP (Polling/WebSocket)** | ✅ |
| Stop bots — **10s retry**, **5s auto-close** on success, pause on error | ✅ |
| KAVACH Positions MarkdownV2 | ✅ (prior session) |

### Gradual rollout (7 gates)

| Gate | Target | Status |
|------|--------|--------|
| **1** | NIFTY LTP feed | 🟡 REST poller coded; **Saturday** operator setup + cache verify |
| **2** | Telegram bots | 🟡 All 3 standalone; Saturday: all bots + simulator together |
| **3** | Dhan positions | 🟡 Live fetch; re-register Monday with new wizard |
| **4** | KAVACH configured | 🟡 ATO in standalone; fresh register after cleanup |
| **5** | Choppy / ATO test (simulated) | ⬜ **Monday** — `GATE5_RUNBOOK.md` |
| **6** | Performance review | Pending |
| **7** | JAGRAN error reporting | 🟡 Standalone OK; live incident paths on Monday |

### Run order (Windows)

**Quick dev (all Phase 1 bots):** `Execution\Start Bots\Phase 1 Start All Robots.bat` · stop with `Execution\Stop Bots\Phase 1 Stop All Robots.bat` · details in `Execution/PHASE1_ROBOT_LAUNCHER.md`

1. **DRISHTI** → `start Drishti.bat` (or Start All) → JWT → **LTP Feed Setup** (pick intervals)
2. **KAVACH** → `start Kavach.bat` → confirm ATO thread in startup log
3. **JAGRAN** → `start Jagran.bat`
4. Optional: `python simulator/app.py` → http://localhost:5001
5. **Status:** `Start Bots\Show Bot Status.bat` or `Stop Bots\Show Bot Status.bat`
6. **Stop:** `stop <Bot>.bat` or **Phase 1 Stop All** — never the window X button

### Saturday checklist

- [ ] Start DRISHTI + KAVACH + JAGRAN together
- [ ] Run simulator in parallel with Telegram bots
- [ ] DRISHTI menu: **Nifty LTP (Polling)** vs **(WebSocket)** labels OK
- [ ] **Batman Complete** → cleanup verified message
- [ ] **/register** — lot picker shows **lots** (e.g. 910 qty → max **14** lots), not 910 buttons

### Monday checklist (Gate 5)

- [ ] Follow **`GATE5_RUNBOOK.md`**
- [ ] Capture ATO cycle ledger + snapshot XLSX
- [ ] Mock breach/retrace via simulator or controlled spot
- [ ] Optional: stale-feed → auto-pause → Resume drill

### Deprecated for next register

Old deployment `batman_2026-05-29_19-09.json` — **do not reuse**; run Batman Complete first.

### Start files (read first after restart)

1. **`CONTEXT.md`** — this master handoff
2. **`GATE5_RUNBOOK.md`** — Monday ATO test
3. **`bat_telegram/bots/kavach/KAVACH_CONTEXT.md`**
4. **`PHASE1_IMPLEMENTATION_PLAN.md`**
5. **`PHASE1_DAILY_LOG_2026-05-30.md`**

### Documentation index

| File | Role |
|------|------|
| `CONTEXT.md` | **Master handoff (this file)** |
| `GATE5_RUNBOOK.md` | Gate 5 mock ATO test + ledger paths |
| `bat_telegram/bots/kavach/KAVACH_CONTEXT.md` | KAVACH handoff |
| `bat_telegram/bots/jagran/JAGRAN_CONTEXT.md` | JAGRAN handoff |
| `bat_telegram/bots/drishti/DRISHTI_CONTEXT.md` | DRISHTI reference |
| `PHASE1_IMPLEMENTATION_PLAN.md` | 7-gate rollout |
| `PHASE1_OPEN_QUESTIONS.md` | Unresolved questions only |
| `bat_telegram/bots/saransh/SARANSH_CONTEXT.md` | **SARANSH handoff — resume tomorrow** |
| `METRICS_SUMMARY.md` §19 | **Complexity & India cost snapshot (2026-05-30)** |
| `SESSION_CAPTURE_LOG.md` | Audit trail |

---

## 16. SARANSH / Phase 1 expansion handoff (2026-05-30 close)

**Done today:** SARANSH design Q&A locked; `@saransh_bm_bot` configured; group **Non Critical Alerts** (`-5163776252`); EOD 15:30; non-critical ≠ JAGRAN.

**Not started:** SARANSH code changes, non-critical incident publisher, cycle ledger XLSX, KAVACH-style UI, SANCHALAK/LAKSHMI wiring.

**Tomorrow (in order):**
1. SANCHALAK token + chat ID (`OQ-SAR-01`)
2. LAKSHMI non-critical enable (`OQ-SAR-02`)
3. Hedge box + register wizard Q&A (`OQ-SAR-03`)
4. 5-year Dhan 1-min replay architecture (`OQ-SAR-04`)
5. SARANSH implementation kickoff (`OQ-SAR-05`)

**Bot tiers (permanent):**
- **Critical → JAGRAN / Batman Alerts:** DRISHTI, KAVACH
- **Non-critical → Non Critical Alerts group:** SARANSH, LAKSHMI

---

## 17. DRISHTI robot hardening + live test handoff (2026-06-01 close)

**Session focus:** Make DRISHTI the most reliable robot — REST LTP retry, feed lifecycle, token intelligence, health observability, process resilience. Operator ran full Telegram button test; logs reviewed together.

### Coded this session (DRISHTI)

| Area | What |
|------|------|
| **REST retry** | `fetch_nifty_ltp_rest_with_retry()` — exponential backoff; explicit HTTP 429; longer delay on rate limits (`core/nifty_ltp.py`) |
| **Feed rate-limit** | 429 cooldown (30s default); does **not** increment failure streak or JAGRAN; keeps last good LTP (`core/nifty_ltp_feed.py`) |
| **Pre-start cleanup** | `run_drishti.py` kills stale `run_drishti.py` PIDs before lock; stop script matches `python*.exe` / `py.exe` |
| **Auto feed config** | First verified token save creates `data/nifty_ltp_feed_config.json` (2s poll, 10s stale) — no manual LTP Feed Setup required |
| **Feed restart on token save** | Clears rate-limit/failure state; immediate poll after Update Token |
| **Deactivate cleanup** | Stops poller + marks cache unhealthy |
| **Feed watchdog** | Every 60s — restarts dead poller task + Telegram notice |
| **Token JWT exp** | `TokenStore.effective_expires_in_hours()` — min(save-age TTL, JWT `exp`); shown in Token Status + Health |
| **Stale-token monitor** | Standalone loop: 20h JAGRAN + 60min expiry warning (mirrors `main.py`) |
| **TYPE 1 reminders** | Suppressed when token valid; only fire when missing/expired/within warning window |
| **Health / alive menu** | Feed block in Health; feed line + token hint on alive menu; poller task status |
| **Telegram resilience** | `run_drishti.py` infinite restart loop on crash/network (5s backoff) |
| **phase1_bot_check** | LTP cache freshness + DRISHTI process count in health report |

**Key files:** `core/nifty_ltp.py`, `core/nifty_ltp_feed.py`, `core/token_store.py`, `bat_telegram/bots/drishti/bot.py`, `bat_telegram/bots/drishti/nifty_feed_integration.py`, `run_drishti.py`, `scripts/stop_bot_common.py`, `scripts/phase1_bot_check.py`, `tests/test_drishti_robot.py`, `tests/test_nifty_ltp*.py`, `tests/test_drishti_feed_integration.py`

**Tests:** 31+ DRISHTI/LTP tests passing (`test_drishti_robot.py` added).

### Architecture (locked — DRISHTI LTP)

```
Background: NiftyLtpWebSocketFeedService (default) or NiftyLtpFeedService (REST) → data/nifty_ltp_cache.json
KAVACH/ATO: resolve_nifty_ltp_from_cache() only — no broker LTP fallback
Telegram "Nifty LTP (Polling)": cache-first when feed running (no duplicate Dhan call)
Telegram "Nifty LTP (WebSocket)": one-shot diagnostic only
TYPE 2 feed failures / stale price: JAGRAN + auto-pause ATO via DrishtiFeedHooks
Legacy _market_monitor_loop: REMOVED (REST feed + hooks replace hourly websocket poll)
```

### Live test evidence (01-Jun-2026 ~12:52–12:54 IST)

| Check | Result |
|-------|--------|
| phase1_bot_check (4 bots) | **PASS** — DRISHTI, KAVACH, JAGRAN, SARANSH |
| Token | Connected, ~22.7h effective expiry, fundlimit OK |
| LTP cache | ~₹23,530, age &lt;5s, `feed_healthy: true`, 0 failures |
| Live REST vs cache | **0.20 pts** delta |
| Telegram buttons (Ping, Polling, Health, Token, WebSocket) | All `answerCallbackQuery` + `sendMessage` **HTTP 200** in logs |
| One HTTP 429 at 12:54:02 | Retry recovered ~10s — **no JAGRAN**, no failure streak |
| `logs/bots/drishti/nifty_ltp/` | Continuous `ok` ticks through test window |

### Known ops issue (fix first tomorrow)

**Duplicate or hidden bot processes** — often 2× `run_*.py` (double-click start bat) or 1× orphan after closing CMD with X. Causes duplicate Telegram polling, stale locks, or DRISHTI 429.

**Fix (all bots):** `Execution\Stop Bots\stop <Bot>.bat` → `Execution\Show Bot Status.bat` must show **STOPPED** → `start <Bot>.bat` **once**. See §3.1; `scripts\bot_status.py all` for agent checks.

### Tomorrow (priority order)

1. **Single DRISHTI instance** — verify after clean stop/start
2. **SARANSH Phase 1** — `run_saransh.py`, Start/Stop bats, non-critical publisher, cycle ledger XLSX (`SARANSH_CONTEXT.md` §13)
3. **OQ-SAR-01** — SANCHALAK token + chat ID
4. **OQ-SAR-03** — Hedge box + register wizard Q&A
5. Optional: bump default poll to **3s** if 429 persists with single instance
6. Gate 5 prep — `GATE5_RUNBOOK.md` when ready for ATO mock test

### Start files (read first after restart)

1. **`CONTEXT.md`** §17 (this handoff)
2. **`bat_telegram/bots/drishti/DRISHTI_CONTEXT.md`** §11–12 (robot + test log)
3. **`bat_telegram/bots/saransh/SARANSH_CONTEXT.md`**
4. **`PHASE1_OPEN_QUESTIONS.md`**
5. **`GATE5_RUNBOOK.md`**

---

## 18. NIFTY LTP stale-cache fix + GIFT probe + validation (2026-06-02 close)

**Session focus:** Operator reported stale NIFTY LTP (~₹23,497 from prior session) after JWT refresh; requested deep fix, audit logging, off-hours validation via GIFT Nifty, and configurable ping staleness thresholds (default **15s** warning / **60s** critical).

### Problem diagnosed

| Symptom | Root cause |
|---------|------------|
| Stale ₹23,497 after token update | Off-hours REST poller idle; token save validated LTP but did not refresh cache |
| Telegram showed old price as OK | Button read stale cache with misleading “healthy” label |
| No post-mortem trail | Audit log existed but lacked source/event columns; GIFT path missing |

### Coded this session

| Area | What |
|------|------|
| **Stale cache fix** | `seed_nifty_ltp_cache()` on token save; off-session marks cache unhealthy; user ping always live-fetches when stale |
| **User ping validation** | `core/nifty_ltp_validation.py` — warning/critical thresholds; JAGRAN `nifty_ltp_stale_cache` incident |
| **Configurable thresholds** | LTP Feed Setup steps 4–5: ping warning (10–60s, default **15**) + critical (30–120s, default **60**); stored in `data/nifty_ltp_feed_config.json` |
| **GIFT Nifty off-hours probe** | `core/gift_nifty_ltp.py` + `core/gift_nifty_probe.py` — Dhan `GIFTNIFTY` security ID **5024**; separate cache `data/gift_nifty_ltp_cache.json` |
| **Telegram** | **GIFT Nifty (probe)** button; alive menu shows GIFT probe line off-hours |
| **Audit logs** | Format: `timestamp,ltp,source,event` under `logs/runtime/…/drishti/logs/nifty_ltp/` — `nifty_ltp_*.log` (production) + `gift_nifty_ltp_*.log` (validation) |
| **Bot resilience** | KAVACH/JAGRAN infinite restart loop (same pattern as DRISHTI) |
| **Logging layout** | Single root `logs/runtime/YYYY-MM/YYYY-MM-DD/` — see `LOGGING_LAYOUT.md` |
| **Debug tooling** | `scripts/diagnose_robot.py`, `ROBOT_DEBUG_PROTOCOL.md`, `.cursor/rules/batman-debug-robot.mdc` |

**Key files:** `core/nifty_ltp_validation.py`, `core/gift_nifty_ltp.py`, `core/gift_nifty_probe.py`, `core/nifty_ltp_feed.py`, `bat_telegram/bots/drishti/nifty_feed_integration.py`, `bat_telegram/bots/drishti/bot.py`, `run_kavach.py`, `run_jagran.py`, `tests/test_nifty_ltp_validation.py`, `tests/test_gift_nifty_ltp.py`

**Tests:** 40+ on validation/GIFT/feed integration (all passing at session close).

### Architecture (locked — updated)

```
NSE hours (09:15–15:30 IST):
  DRISHTI NiftyLtpFeedService (REST) → data/nifty_ltp_cache.json → KAVACH/ATO read only

Off-hours:
  NIFTY spot REST = last close / indicative (not continuous session)
  DRISHTI GiftNiftyProbeService → data/gift_nifty_ltp_cache.json (validation only)
  User Nifty LTP ping → live REST fetch + cache seed (never show stale cache)

User ping rules (configurable):
  ≤ feed freshness (poll×3) → cache OK during market
  ≥ warning age (default 15s) → ⚠️ + live fetch
  ≥ critical age (default 60s) → 🔴 JAGRAN incident + live fetch
```

### Live evidence (02-Jun-2026 ~01:24–01:57 IST, off-market)

| Check | Result |
|-------|--------|
| Stale cache before fix | ₹23,497.15 · age ~12.5h · `feed_healthy: true` |
| Live REST after token | ₹23,382.6 |
| GIFT NIFTY REST | ₹23,690.0 (security ID 5024) |
| DRISHTI + GIFT probe start | Both tasks start; GIFT polls every 2s off-hours |

### Ops notes

- **Cursor background shells** exit with code 1 after minutes — not a bot crash. Use `Execution\Start Bots\start *.bat` for overnight runs (§3.1 — not raw `python run_*.py`).
- **KAVACH off-hours ERROR** `ATO startup scan: NIFTY LTP cache stale` — expected, non-fatal.
- **Reconfigure thresholds:** DRISHTI → **LTP Feed Setup** → steps 4 (warning) + 5 (critical).

### Start files (read first after restart)

1. **`CONTEXT.md`** §18 (this handoff)
2. **`bat_telegram/bots/drishti/DRISHTI_CONTEXT.md`** §13–14
3. **`NIFTY_LTP_POLICY.md`**
4. **`LOGGING_LAYOUT.md`**
5. **`ROBOT_DEBUG_PROTOCOL.md`**

---

## 20. UAT virtual broker + live session + E2E agent (2026-06-03 close)

**Operator intent:** Production-like testing on laptop without real Dhan orders. Live NIFTY from DRISHTI; positions from Sensibull screenshot; real KAVACH register wizard + ATO logic via **ShadowBroker**.

### 20.1 Three runtime modes (locked)

| Mode | Set | Data | Logs | Positions | Orders |
|------|-----|------|------|-----------|--------|
| **dev** | `Mode\Set-Dev.bat` | `data/dev/` | `logs_dev/` | Dhan read (optional) | Blocked |
| **uat** | `Mode\Set-UAT.bat` | `data/uat/` | `logs_uat/` | **Cursor chat → `positions.json`** (primary); OCR fallback | Virtual only |
| **prod** | `Mode\Set-Prod.bat` | `data/prod/` | `logs_prod/` | Live Dhan | Live Dhan (VPS later) |

Config: `config/batman_mode.json` — do not edit by hand; use `Mode\*.bat` → `scripts/set_batman_mode.py`.

### 20.2 UAT architecture (built this phase)

| Piece | Path / entry |
|-------|----------------|
| Screenshot drop folder | `uat/deployed_positions/` (any PNG/JPG name) → `positions.json` |
| OCR ingest | `core/uat_ingest.py` · `backtest_engine/uat/sensibull_parser.py` |
| Virtual broker | `backtest_engine/shadow/shadow_broker.py` via `core/broker_factory.py` |
| KAVACH UAT UX | Environment button, register preamble, ingest on Register |
| Instrument resolve | `backtest_engine/resolver/instrument_master.py` + JWT |
| Sample fixture | `backtest_engine/fixtures/sensibull/jun9_2026_sensibull.json` (reference only) |
| Deployments (UAT) | `data/uat/deployments/batman_*.json` |
| State (UAT) | `data/uat/batman_state.json` |

**Canonical test book (Sensibull):** spot ~23483, expiry **09 Jun 2026**, legs pe_sell 23200×2, pe_buy 23250×1, ce_buy 23750×1, ce_sell 23800×2. ATO protect 23150 PE / 23850 CE appear only after simulated ATO BUY.

**Rules locked:** lot size 65; new screenshot while armed → no auto-replace (Batman Complete then re-register); old `simulator/` Flask app out of scope.

### 20.3 Bugs fixed during live UAT session (2026-06-03)

1. **Register “stuck”** — synchronous OCR (~90s) blocked Telegram event loop; mid-wizard state ignored Register taps.
   - **Fix:** `asyncio.to_thread` for ingest + broker refresh; progress message; skip OCR if fresh `positions.json`; UAT skips JWT gate for ShadowBroker; `allow_reentry=True` + Register in wizard fallbacks.
   - **Files:** `bat_telegram/bots/kavach/bot.py`, `bat_telegram/bots/kavach/register_wizard.py`
2. **ATO restore wrong folder** — hardcoded `data/deployments/` instead of `data/uat/deployments/`.
   - **Fix:** `modules/ato_protection.py` uses `deployments_dir()` from `core.batman_mode`.
   - **Note:** Restart KAVACH after deploy so ATO picks up mode path on boot.
3. **KAVACH ORPHAN / lock** — stale `data/uat/kavach.lock` (dead PID) blocked restarts.
   - **Recovery:** `Execution\Stop Bots\stop Kavach.bat` → delete stale lock if needed → `start Kavach.bat` → **Show Bot Status** = RUNNING with lock.

### 20.4 Autonomous UAT testing (agent — no manual Telegram)

| Artifact | Purpose |
|----------|---------|
| **`UAT_E2E_AGENT.md`** | Copy-paste Cursor Agent prompt + full loop |
| **`scripts/run_uat_e2e_verification.py`** | Headless gate (mode, JWT, fixture, pytest, register smoke, bot check, log scan) |
| **`Execution\Run UAT E2E Verification.bat`** | One-click verification |
| **`tests/test_uat_ingest.py`** | Ingest helper tests |

**Agent command (after every code change):**

```powershell
Mode\Set-UAT.bat
.venv\Scripts\python.exe scripts\run_quality_gates.py
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

**Last verification run (2026-06-03):** ALL PASSED (JWT OK, fixture OK, pytest OK, register wizard smoke OK). KAVACH process status was ORPHAN — clean stop/start before live wizard.

**Cursor Agent:** new chat → `@UAT_E2E_AGENT.md` → paste prompt from that file. Optional: `/loop 10m` + same prompt for recurring checks.

### 20.5 Session state at close (resume from here)

> **Superseded by §25 (2026-07-11)** — current UAT state, fast path, and active deployment are in **§25**.

| Item | Status |
|------|--------|
| Mode | **uat** |
| Screenshot | `uat/deployed_positions/sensibull_test.png` |
| `positions.json` | **OK** — 4 legs written |
| `data/uat/deployments/batman_*.json` | **None yet** — Register wizard not confirmed / armed |
| JWT | Valid in `data/access_token.json` (~refreshed 2026-06-03 02:26 IST) |
| DRISHTI | Was RUNNING; LTP REST 200 OK in `logs_uat/.../drishti/` |
| JAGRAN | Was RUNNING |
| KAVACH | Was ORPHAN (PIDs without lock) — **fix first tomorrow** |
| ATO | Waiting for `deployment.confirmed` |

### 20.6 Tomorrow — operator sequence (minimal)

1. `Mode\Set-UAT.bat` (if not already uat).
2. `Execution\Stop Bots\Phase 1 Stop All Robots.bat` → confirm **STOPPED**.
3. `Execution\Start Bots\Phase 1 Start All Robots.bat` → confirm **RUNNING** (fix KAVACH lock if ORPHAN).
4. DRISHTI: confirm JWT if `run_uat_e2e_verification.py` reports `dhan_jwt FAIL`.
5. KAVACH: `/start` → fresh menu → **Register** once → confirm legs → finish wizard → arm.
6. Agent (optional): run `Execution\Run UAT E2E Verification.bat` before/after register.

**Say to Agent tomorrow:** *"Continue UAT from CONTEXT.md §20 — run E2E verification and help complete Register if needed."*

### 20.7 Log paths (UAT mode)

```
logs_uat/runtime/YYYY-MM/YYYY-MM-DD/kavach/logs/all.log
logs_uat/runtime/YYYY-MM/YYYY-MM-DD/drishti/logs/all.log
logs_uat/runtime/YYYY-MM/YYYY-MM-DD/jagran/logs/all.log
```

Search for: `UAT_INGEST`, `ShadowBroker`, `wizard_`, `ATO`, `ERROR`, `deployment.confirmed`.

### 20.8 Still pending (not done)

- [ ] Complete live Register → `batman_*.json` in `data/uat/deployments/`
- [ ] Arm Batman; observe ATO on live NIFTY (virtual fills)
- [ ] UAT scenario matrix UAT-01… (manual or agent-led)
- [ ] Prod/VPS path — prep only; laptop stays uat/dev
- [ ] Optional: move startup OCR in `run_kavach.py` to thread + skip-if-fresh (same as Register fix)

### 20.9 Daily test execution (Excel matrix — 2026-06-03)

| Item | Path |
|------|------|
| **Run suite** | `scripts/run_uat_daily_test_suite.py` or `Execution\Run Daily UAT Test Suite.bat` |
| **Excel matrix** | `daily_test_execution/test_matrix.xlsx` (sheet `Matrix` + `Daily_YYYY-MM-DD`) |
| **Latest summary** | `daily_test_execution/LATEST_RUN.md` (link to Excel after each run) |
| **Case catalog** | `daily_test_execution/UAT_TEST_CATALOG.md` · runners in `core/uat_daily_tests.py` |
| **pytest** | `tests/test_uat_daily_matrix.py` (31 cases UAT-D00…UAT-D30) |
| **Daily protocol** | `daily_test_execution/UAT_DAILY_TEST_PROTOCOL.md` |
| **Suite logs** | `daily_test_execution/logs/YYYY-MM/YYYY-MM-DD/daily_suite_*.log` |

Covers: mode, screenshot book, JWT, shadow load + **virtual order**, live LTP (market hours), bot process locks, logs, Register smoke, **all menu buttons**, performance (OCR ms).

### 20.10 Key docs map

| Doc | Role |
|-----|------|
| `UAT_E2E_AGENT.md` | Agent autonomous loop + daily suite |
| `AGENTS.md` | General agent playbook |
| `TESTING_PROTOCOL.md` | Verify loop (4 cycles) |
| `Mode/README.md` | Mode switching |
| `GATE5_RUNBOOK.md` | Mock ATO (related; UAT uses shadow orders) |
| `backtest_engine/tools/prepare_uat_session.py` | Manual UAT folder check |
| **`UAT_CHAT_POSITIONS.md`** | **Daily shortcut — paste Sensibull screenshot in Cursor** |
| `skills/uat-sensibull-from-chat/SKILL.md` | Agent skill for chat → `positions.json` |

---

## 21. UAT Cursor-chat positions + Register + display (2026-06-04 close)

**Operator decision:** Disk OCR on Sensibull PNGs is unreliable. **Primary UAT book path:** paste screenshot in **Cursor chat** → agent writes `uat/deployed_positions/positions.json` (`source: cursor_chat`) → **Register** in KAVACH (no OCR wait). OCR remains optional fallback only.

### 21.1 Daily operator shortcut (locked)

Paste in Cursor with Sensibull screenshot attached:

```text
UAT POSITIONS. Read the Sensibull screenshot (note expiry + 4 legs) and write positions.json for UAT Register.
@uat-sensibull-from-chat
```

Then wait for agent: **`OK: ...positions.json`** → tap **Register** in KAVACH (UAT). Optional validate: `Execution\Apply UAT Chat Positions.bat`.

### 21.2 Code paths (built / changed 2026-06-04)

| Piece | Path / behavior |
|-------|------------------|
| Chat fixture writer | `scripts/write_uat_chat_positions.py` · `core/uat_chat_positions.py` |
| Register ingest | `ingest_uat_for_register()` — **cursor_chat first**, OCR only if missing |
| Startup ingest | `ingest_uat_at_startup()` — **skip OCR** when valid `cursor_chat` JSON |
| Register cleanup | `core/uat_register_cleanup.py` — archives deployments; **keeps** `cursor_chat` `positions.json` |
| Position display | `core/uat_position_enrich.py` — **expiry from fixture** (any weekly), Sensibull prices, live LTP via `marketfeed` + `core/nifty_option_expiry.py` |
| Telegram `/positions` | Refreshes fixture; shows `NIFTY 09 Jun 2026 {strike} {CE\|PE}` not `Jun2026`; no **₹nan** |
| OCR verify | `scripts/verify_ocr_deps.py` |
| Phase 1 Start All | UAT default wait **180s** (was 120s) |
| Bad PNGs | Move to `uat/deployed_positions/OLD/` — do not leave `Screenshot_121.png` in main folder |

**Removed (by design):** reuse of stale `positions.json` when OCR fails; “fresh positions.json skip OCR” on Register without chat source.

### 21.3 Current Sensibull book on disk (resume)

| Field | Value |
|-------|--------|
| `positions.json` | `source: cursor_chat` · `expiry_date: 2026-06-09` · `expiry_label: 09 Jun 2026` |
| Legs (09 Jun 2026) | pe_sell 22750×2 @ 17.55 · pe_buy 22800×1 @ 21.05 · ce_buy 23350×1 @ 220.30 · ce_sell 23400×2 @ 191.80 |
| Screenshot ref | `uat/deployed_positions/sensibull_chat_latest.png` |
| `data/uat/deployments/batman_*.json` | **None confirmed** — Register wizard started 2026-06-04 ~10:26 IST; finish PE/CE wizard steps |

**Display check (after code fix):** `/positions` should show **4 legs**, expiry **09 Jun 2026**, all prices filled (not 5 legs, not 23450 @ nan).

### 21.4 Session state at close (2026-06-04)

| Item | Status |
|------|--------|
| Mode | **uat** (`config/batman_mode.json`) |
| Phase 1 bots | **All STOPPED** at close (Start All had timed out earlier) |
| KAVACH lock | Ghost lock **cleared** — safe to start clean |
| JWT | Was valid earlier in session — re-check via DRISHTI / `run_uat_e2e_verification.py` before Register |
| Register log | `UAT register: using cursor_chat positions.json (skip OCR)` — **success** at ~10:26 IST |
| Startup log | `UAT startup: cursor_chat positions.json ready` — after fix |

### 21.5 Next session — operator sequence

1. `Mode\Set-UAT.bat`
2. `Execution\Stop Bots\Phase 1 Stop All Robots.bat` → **STOPPED**
3. `Execution\Start Bots\Phase 1 Start All Robots.bat` → wait up to **180s** → **RUNNING**
4. If new Sensibull book: Cursor shortcut (§21.1) → confirm `positions.json` updated
5. KAVACH: **Positions** → verify 4 legs + prices → **Register** → complete wizard → arm
6. Agent (optional): `.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py --ingest`

**Say to Agent:** *"Continue UAT from CONTEXT.md §21 — Start All bots, verify Positions display, complete Register if needed."*

### 21.6 Known issues / do not regress

- Do **not** rely on OCR for daily book; use **chat path**
- Partial PNGs in `deployed_positions/` slow/fail startup if `cursor_chat` JSON missing
- **₹nan** was stale broker + wrong strike (23450) — fixed by refresh + enrich; always tap **Positions** after new JSON
- Phase 1 **Start All timeout** if KAVACH ORPHAN during long OCR — mitigated by §21.2 startup skip

### 21.7 Still pending

- [ ] Complete Register → armed `data/uat/deployments/batman_*.json` (if not already armed — check D21 state)
- [ ] Gate 5 / ATO on virtual fills with live NIFTY
- [x] UAT daily matrix — **31 cases** UAT-D00…D30 + suite logs (§22)

---

## 23. Bot independence architecture (locked 2026-06-05)

**Operator decision:** Keep DRISHTI, KAVACH, and JAGRAN as **independent robots** — organized, not mixed.

### 23.1 What stays separate (locked)

| Robot | Owns | Must not absorb |
|-------|------|-----------------|
| **DRISHTI** | Dhan JWT, NIFTY LTP feed, token/health UI | KAVACH register, ATO, deployment state |
| **KAVACH** | Register, ATO, positions UI, UAT shadow book | DRISHTI LTP poll loop, JAGRAN incident routing |
| **JAGRAN** | Critical incidents, EOD digest, error fan-in | Trading logic, broker sessions |

### 23.2 Explicitly rejected

- **Merging DRISHTI + KAVACH** into one process to avoid cache staleness — rejected; use sequential start + `startup_gates` + shared JSON cache instead.
- Running Phase 1 from `main.py` on the laptop — rejected; use `Execution/Start Bots/` only.
- Cross-bot process kill — each bot kills **only its own** `run_*.py` tree (`core/bot_instance_guard.py`).

### 23.3 How independent bots stay reliable (implemented)

| Concern | Independent solution (no merge) |
|---------|----------------------------------|
| Duplicate instances | `bootstrap_exclusive_bot()` per `run_*.py` |
| Start order | `phase1_start_all.py`: DRISHTI → gate → KAVACH → JAGRAN |
| LTP for ATO | DRISHTI writes `data/nifty_ltp_cache.json`; KAVACH reads only |
| Register vs ATO race | `core/deployment_lock.py` in KAVACH + ATO thread |
| Restart continuity | UAT session bundle + ATO restore from deployment file |
| Daily ops | `scripts/run_daily_health.py` + `phase1_post_start_verify.py` |

### 23.4 Independence-friendly improvements

| # | Feature | Status | Module |
|---|---------|--------|--------|
| 1 | **NIFTY cache heartbeat** — `ready_for_consumers`, `cache_age_seconds`, `collector` in `nifty_ltp_cache.json` | **CODED** | `core/nifty_ltp_feed.py`, `cache_consumer_status()` |
| 2 | **Per-bot health JSON** — `data/runtime/{bot}/health.json` every 30s | **CODED** | `core/bot_health.py`, `run_*.py` |
| 3 | **JAGRAN severity routing** — DRISHTI feed=warning, KAVACH order fail=critical | **CODED** | `core/incident_severity.py`, `incident_tracker.py`, `incident_publisher.py` |
| 4 | **ATO idempotency keys** — `YYYY-MM-DD:CE|PE:BUY:symbol` in state | **CODED** | `core/ato_idempotency.py`, `modules/ato_protection.py` |
| 5 | **Canary register dry-run** — validate 4 legs + protect symbols before arming (see §23.7) | **BACKLOG** | operator decision pending |
| 6 | **Market data guard** — cache-first position enrich; no ×50 option chain hammer | **CODED** | `core/market_data_guard.py`, `core/uat_position_enrich.py`, `kavach/bot.py` |

### 23.5 Market data guard (cache-first — no DRISHTI calls from KAVACH)

**Operator intent (2026-06-05):** KAVACH must not behave as if it “calls DRISHTI.” When ~50% of premiums are already in the Sensibull fixture (`positions.json`) or broker avg, live Dhan/Tradehull calls are wasteful and slow. Guard layer enforces **disk-first, exact-leg-only** enrichment.

**Hard rule:** KAVACH **never imports or RPCs DRISHTI**. Coordination is disk-only:
- NIFTY spot → `data/nifty_ltp_cache.json` (DRISHTI writer, KAVACH/ATO reader)
- UAT premiums → `uat/deployed_positions/positions.json` fixture legs
- JWT → `data/access_token.json`

| Guard | API | Behaviour |
|-------|-----|-----------|
| Skip live quotes | `should_skip_live_quotes()` | True when broker avg + fixture cover all legs — no REST |
| Enrich debounce | `get_cached_enrich()` / `set_cached_enrich()` | Same positions fingerprint → return cached enrich for **2s** |
| Quote throttle | `allow_live_option_quotes()` | Max one REST burst per **2s**; exact missing legs only |
| Option chain ×50 | `option_chain_fallback_enabled()` → **False** | `try_option_chain_premiums(num_strikes=50)` **disabled** unless future opt-in |
| Fixture-first | `legs_still_missing_after_fixture()` | Apply `fixture_price_map` before any API |
| KAVACH Positions | `_enrich_positions_list()` | Sets `chain_broker=None` when skip guard fires |
| Enrich pipeline | `enrich_nifty_positions()` | Order: broker avg → fixture → `get_nifty_option_ltps` (exact legs) → chain fallback only if opt-in |

**NIFTY spot for ATO (not position premiums):**
- `resolve_nifty_ltp_from_cache()` reads `nifty_ltp_cache.json`
- `cache_consumer_status()` exposes `ready_for_consumers`, `cache_age_seconds`
- After `ltp_failure_alert_threshold` (default 5) consecutive stale reads: JAGRAN alert + **auto-pause** algo (`algo.pause_reason=nifty_ltp_cache_stale`)
- Config key `ltp_failure_pause_after` (default = threshold) controls pause timing

**Tests:** `tests/test_market_data_guard.py` — fixture-complete enrich never calls broker; throttle isolation via `reset_market_data_guard_for_tests()` autouse in `tests/conftest.py`.

**Before vs after:**

| Before | After |
|--------|-------|
| Positions tap could REST-quote all legs | REST only for legs still at `avg_price=0` after fixture |
| Fallback to Tradehull 50-strike chain | Chain fallback **off** by default |
| Repeated enrich on every Telegram refresh | 2s fingerprint debounce |
| “Slow DRISHTI” perception | Usually stale cache or duplicate DRISHTI — not cross-process calls |

### 23.6 DRISHTI vs KAVACH — keep separate (operator lock 2026-06-05)

DRISHTI practical roles today: **JWT/token** (moving to TOTP/30-day access later), **NIFTY REST poll → cache file**, **health/diagnostic UI**. KAVACH reads cache only for ATO — never imports DRISHTI. Slowness when “accessing DRISHTI” is usually **KAVACH waiting on stale cache** or **duplicate bot instances**, not cross-process RPC.

**Merge rejected** — see §23.2. NIFTY feed is in-process WebSocket inside DRISHTI with runtime REST failover.

### 23.7 Canary register (idea #5 — for operator review)

**What it is:** On Register **Confirm**, KAVACH runs a **dry-run** first: read `positions.json` + deployment draft, validate 4 legs, strikes, protect symbols, broker qty — **without** setting `deployment.confirmed=True` or placing orders. Operator sees ✅ preview or ❌ errors; only a second **Arm** tap (or auto-arm if preview passes) activates ATO.

**Why useful:** Catches wrong screenshot week, missing leg, or bad protect symbol before ATO polls with bad state.

**Why optional:** Adds one extra Telegram step; you may prefer current single Confirm if agent always prepares `positions.json` correctly.

**Your call:** Enable always / enable via param flag / skip.

### 23.8 Key disk artifacts (independence contracts)

| Artifact | Writer | Reader(s) | Purpose |
|----------|--------|-----------|---------|
| `data/access_token.json` | DRISHTI | KAVACH broker | Dhan JWT |
| `data/nifty_ltp_cache.json` | DRISHTI | KAVACH ATO | NIFTY spot + heartbeat fields |
| `data/runtime/{bot}/health.json` | each `run_*.py` | agent scripts, future DRISHTI fleet | PID, mode, last heartbeat |
| `data/{mode}/batman_state.json` | KAVACH | KAVACH ATO | deployment + algo flags |
| `uat/deployed_positions/positions.json` | agent/operator | KAVACH UAT enrich + register | Sensibull fixture book |
| `data/uat/deployments/batman_*.json` | KAVACH | KAVACH ATO restore | session bundle |

UAT logs: `logs_uat/runtime/YYYY-MM/YYYY-MM-DD/{robot}/logs/all.log` and `{robot}/errors/all_errors.log`.

### 23.9 Agent rule

When proposing architecture changes: prefer **clear ownership boundaries**, **disk/event contracts**, **sequential launcher gates**, and **cache-first guards** — not combining processes.

---

## 22. Resume after restart (2026-06-05 save)

**Say to Agent:** *"Continue UAT from CONTEXT.md §22."* or *"Follow §23 independence + market guard."*

### 22.1 What was done this session (saved on disk)

| Topic | Outcome |
|-------|---------|
| **Independence lock (§23)** | Three separate OS processes — **DRISHTI+KAVACH merge rejected**; disk-only coordination |
| **Infra hardening (§7.2)** | `bot_instance_guard`, `deployment_lock`, `startup_gates`, sequential `phase1_start_all`, post-start verify, daily health, session bundle, REST throttle, protect-symbol derive |
| **Independence features 1–4** | Cache heartbeat, `health.json`, JAGRAN severity, ATO idempotency — all **CODED** |
| **Market data guard (§23.5)** | `core/market_data_guard.py` — fixture-first, 2s debounce/throttle, ×50 chain **off**, KAVACH never calls DRISHTI |
| **ATO stale cache** | Consecutive failures → JAGRAN alert + auto-pause; no Dhan spot poll from KAVACH |
| **5-Jun log audit** | Positions MarkdownV2, CE protect race on Batman Complete, JAGRAN error handler — fixed; bots verified RUNNING post-restart |
| **4-Jun UAT audit** | Issues/resolutions in §21 + `SESSION_CAPTURE_LOG` 2026-06-04/05 |
| **Option LTP** | Live via `POST /marketfeed/ltp` + `NSE_FNO` securityIds — **not** Tradehull symbol strings. See `DHAN_API_CONTEXT.md`, `scripts/probe_dhan_option_ltp.py` |
| **Dynamic expiry** | Any weekly from screenshot/`positions.json` — `core/nifty_option_expiry.py` |
| **Daily UAT tests** | 31 cases, Excel matrix, `UAT_DAILY_TEST_PROTOCOL.md`, logs under `daily_test_execution/logs/` |
| **Canary register (#5)** | Documented §23.7 — operator decision pending (always / flag / skip) |

### 22.2 On disk now

| Item | Value |
|------|--------|
| Mode | **uat** |
| Book | `uat/deployed_positions/positions.json` — cursor_chat, expiry **2026-06-09**, 4 legs |
| JWT | `data/access_token.json` — last saved **2026-06-04 09:08 IST** (~17h at last suite run); refresh via DRISHTI if expired |
| Last daily suite | `20260605_020947` — 19 PASS / 1 FAIL (D21, fixed in code after run) / 11 SKIP — log: `daily_test_execution/logs/2026-06/2026-06-05/daily_suite_20260605_020947.log` |
| Bots | **Assume STOPPED** after laptop restart |

### 22.3 Next session sequence

1. `Mode\Set-UAT.bat`
2. `Execution\Stop Bots\Phase 1 Stop All Robots.bat` → STOPPED
3. DRISHTI: Update Token if probe/suite reports JWT fail
4. `Execution\Start Bots\Phase 1 Start All Robots.bat` → wait **180s** → RUNNING
5. New Sensibull week? → Cursor shortcut (`UAT_CHAT_POSITIONS.md`) → update `positions.json`
6. **Full daily suite (market hours):** `.venv\Scripts\python.exe scripts\run_uat_daily_test_suite.py`
7. KAVACH: Positions → Register (if needed) → arm → Gate 5 / ATO observe

### 22.4 Key paths

| Doc / tool | Path |
|------------|------|
| Independence + market guard | **§23** (authoritative architecture lock) |
| Market guard module | `core/market_data_guard.py` |
| Bot health files | `data/runtime/{drishti,kavach,jagran}/health.json` |
| NIFTY cache | `data/nifty_ltp_cache.json` |
| Daily protocol | `daily_test_execution/UAT_DAILY_TEST_PROTOCOL.md` |
| Case list | `daily_test_execution/UAT_TEST_CATALOG.md` |
| Latest run | `daily_test_execution/LATEST_RUN.md` |
| Option probe | `scripts/probe_dhan_option_ltp.py` |
| E2E gate | `scripts/run_uat_e2e_verification.py` |
| Post-start verify | `scripts/phase1_post_start_verify.py` |
| Daily health | `scripts/run_daily_health.py` |

---

## 19. Project size, structure, and complexity (locked 2026-06-02)

Authoritative live numbers: run **`python scripts/project_stats.py --pytest`** from repo root.  
Re-run after major merges; paste JSON with `--json` if agents need machine-readable output.

### 19.1 Snapshot (Batman app scope — default)

**Scope `batman`:** excludes `Dhan/` archive, `logs/`, `data/`, `Dependencies/`, `.cursor` caches.

| Metric | Count |
|--------|------:|
| Directories | 61 |
| Files | 342 |
| Python files | 138 |
| Python LOC | 35,982 |
| Production Python | 111 files / 30,930 LOC |
| Test Python | 27 files / 5,052 LOC (14.0% of app Python) |
| Markdown docs | 51 files / 12,068 lines |
| Launchers (`.bat` / `.ps1`) | 18 files / 1,509 lines |
| **App + docs (approx.)** | **~48,050 lines** |
| Pytest tests collected | **303** |

**Runtime artifacts (not in app LOC):** `logs/` ~242 files · `data/` ~125 files (counts drift daily).

**Reference only (excluded from Batman totals):** `Dhan/` — 34 top-level `.py` snippets in tree; full archive may contain thousands of `.py` under an embedded venv — **not** counted as authored Batman code.

### 19.2 Other scopes

| Scope | Flag | Directories | Files | Python files | Python LOC |
|-------|------|------------:|------:|-------------:|-----------:|
| Batman app | *(default)* | 61 | 342 | 138 | 35,982 |
| Source tree | `--scope source` | 83 | 399 | 172 | 36,897 |
| Full disk | `--scope full` or `--full` | 159 | 773 | 172 | 36,897 |

`source` adds small `Dhan/` snippets and extra root docs; `full` adds configs, DBs, images, and non-runtime assets on disk.

### 19.3 Python LOC by top-level folder (Batman scope)

| Folder | .py files | LOC | Role |
|--------|----------:|----:|------|
| `bat_telegram/` | 22 | 9,240 | Phase 1 Telegram bots + incident publisher |
| `core/` | 36 | 6,860 | Shared runtime (broker, LTP, logging, launcher, incidents) |
| `tests/` | 27 | 5,052 | Automated tests |
| `simulator/` | 2 | 3,143 | Simulator UI/backend |
| `tools/` | 2 | 2,846 | Inventory / utilities |
| `modules/` | 8 | 2,837 | Trading modules (e.g. ATO protection) |
| `scripts/` | 24 | 2,586 | Ops (start/stop, incidents, **project_stats**) |
| `bot/` | 11 | 2,403 | Legacy reference (retired; see §3) |
| `main.py` + `run_*.py` | 4 | 803 | Entrypoints |

### 19.4 Largest Python files (complexity hotspots)

| LOC | File |
|----:|------|
| 3,170 | `bat_telegram/bots/kavach/bot.py` |
| 2,643 | `tools/generate_file_inventory.py` |
| 2,618 | `simulator/app.py` |
| 1,542 | `bat_telegram/bots/drishti/bot.py` |
| 1,538 | `tests/test_modules.py` |
| 1,478 | `modules/ato_protection.py` |
| 1,193 | `bat_telegram/bots/drishti/nifty_feed_integration.py` |
| 861 | `core/nifty_ltp_feed.py` |
| 767 | `core/incident_tracker.py` |
| 725 | `bat_telegram/bots/kavach/register_wizard.py` |

Several bots/modules are **1,000–3,000+ LOC** per file — primary maintainability risk; mitigated by **303** pytest tests.

### 19.5 Complexity summary (qualitative)

| Dimension | Assessment |
|-----------|------------|
| **Architecture** | Medium–high: 3 Phase 1 robots + shared `core/`, incident domains, NIFTY LTP policy, Windows `.bat` launchers (§3.1) |
| **Operational** | High: dated `logs/runtime/…` trees, incident CSVs, deployment logs, per-bot `token.env` |
| **Code structure** | Elevated in monolithic bot files (KAVACH, DRISHTI) and `ato_protection.py` |
| **Test surface** | Strong for size — 303 tests, ~14% of app Python LOC in `tests/` |
| **Quality gate** | §7 — ruff clean; pytest count should match `project_stats.py --pytest` |

### 19.6 `scripts/project_stats.py` usage

```text
python scripts/project_stats.py
python scripts/project_stats.py --pytest
python scripts/project_stats.py --scope source
python scripts/project_stats.py --full
python scripts/project_stats.py --top 20 --json
```

| Flag | Effect |
|------|--------|
| *(default)* | Batman app scope (§19.1) |
| `--scope source` | Include `Dhan/` snippets; still exclude `logs/`, `data/` |
| `--full` | Entire repo on disk (minus `.git`, caches) |
| `--pytest` | Append pytest `--collect-only` count |
| `--top N` | List N largest `.py` files (default 12) |
| `--json` | Machine-readable report on stdout |

**One-line summary:** ~**36k** Python LOC + ~**12k** markdown ≈ **~48k** project content lines; **303** tests; **~61** source dirs / **~342** app files (Batman scope).

---

## 24. SARANSH Phase 1 implementation complete (2026-06-05)

**Authoritative status:** `SARANSH_IMPLEMENTATION_STATUS.md`

### Delivered (P0–P5)

| Area | Detail |
|------|--------|
| Launcher | `run_saransh.py`, `start Saransh.bat`, `stop Saransh.bat` |
| ATO feed | `core/ato_cycle_feed.py` — KAVACH writes JSONL + state; signed point impact |
| Reporting | `core/saransh_reporting.py` — ATO Cycle table, XLSX, UAT PnL disclaimer |
| Session sync | `core/saransh_session_sync.py` — register/complete hooks; **always** restart SARANSH (OQ-P1-21) |
| Telegram | Menu: ATO Cycle, Daily Summary, Status — **Non Critical Alerts** only; **no JAGRAN** |
| EOD | **15:35 IST**, `is_trading_day()` only |
| Tests | `tests/test_saransh_*.py`, `test_ato_cycle_feed.py` |

### Gate 5 remaining

All **four** bots RUNNING + UAT shadow-book ATO cycle → verify `data/uat/analytics/ato/ato_cycle_feed.jsonl` + SARANSH ATO Cycle button (OQ-P1-23: no live Dhan positions required).

### Next wave — DRISHTI / KAVACH LTP (operator intent, **not started**)

Operator may explore **merging DRISHTI+KAVACH** and **websocket vs REST poll** LTP by user discretion. This **conflicts with §23.1–23.2** until a new design Q&A and explicit scope change. **Do not code merge/websocket until design is locked.**

---

## 25. UAT fast path + live Register session (2026-07-11 close)

**Operator intent:** Daily Sensibull screenshot → `positions.json` → **Register** in KAVACH **without** stop/start all bots, 180s wait, or full daily test suite. Agent executes; operator taps Register only.

### 25.1 Fast UAT workflow (locked — default for book changes)

| Artifact | Purpose |
|----------|---------|
| **`FAST_UAT_PROMPT.md`** | Copy-paste Agent prompt (attach screenshot) |
| **`UAT_CHAT_POSITIONS.md`** | FAST PATH section at top; FULL daily prompt below |
| **`scripts/quick_uat_positions_gate.py`** | ~15s gate: validate JSON, `validate_fixture --skip-chain`, bot RUNNING check, disk cleanup only |
| **`Execution\Quick UAT Positions.bat`** | One-click launcher for quick gate |
| **`skills/uat-sensibull-from-chat/SKILL.md`** | Agent skill — uses quick gate, no restart |

**Architecture fact:** KAVACH reloads the book **in-process** on Register tap (`ingest_uat_for_register` → `cursor_chat` skip OCR → `refresh_fixture_positions`). **No restart** when bots already RUNNING.

**Agent command (book change only):**

```powershell
.venv\Scripts\python.exe scripts\quick_uat_positions_gate.py
```

**Do NOT** run quick gate as a health check on an already-confirmed session — `prepare_uat_register_fresh` resets disk `batman_state.json` (KAVACH in-memory may still be armed until restart).

**Use FULL UAT** (`UAT_CHAT_POSITIONS.md` daily prompt + `run_uat_e2e_verification.py`) when: KAVACH/DRISHTI code changed, bots dead/ORPHAN, JWT broken, first boot wanting full log proof, or operator says **FULL UAT**.

### 25.2 Bugs fixed this session

| Issue | Root cause | Fix |
|-------|------------|-----|
| `/register` `no_valid_token` | JWT expired (`saved_at=2026-06-25`); UAT ShadowBroker blocked at startup | JWT refreshed via DRISHTI; `run_kavach.py` UAT starts ShadowBroker from fixture even if JWT save-age expired; `_try_bootstrap_uat_broker()` on `/register` |
| Batman Complete auto-register crash (00:45 IST) | Tuple passed where `startswith` expected on wizard step target | `_str_step_target()` in `register_wizard.py` — applied in `_qheader`, `_buffer_step_title`, `_side_enabled`, `wizard_buffer_mode`, `_advance_after_buffer*` |
| Session bundle persist skipped (01:23 IST) | `workspace_root(_DEPLOY_DIR.parent.parent)` — wrong arity | `bat_telegram/bots/kavach/bot.py` → `workspace_root()` |
| KAVACH ORPHAN / duplicate PIDs | Overlapping `run_kavach.py` without lock | `stop_kavach.py --silent` → single start with `BATMAN_LAUNCHED_VIA_BAT=1` |

**Tests:** `tests/test_kavach_scenarios.py` — **36 passed** after fixes.

### 25.3 Active deployment (confirmed 2026-07-11 01:23 IST)

| Item | Value |
|------|-------|
| Mode | **uat** |
| Deployment file | `data/uat/deployments/batman_2026-07-11_01-23.json` |
| Scope | **PE only** (`pe_enabled=true`, `ce_enabled=false`, `ato_manage_sides=pe`) |
| `deployment.confirmed` | **True** (disk + in-memory after restore) |
| ATO | **Armed** — monitoring scheduled **09:25 IST** |
| Session bundle | `data/uat/session_bundle/batman_2026-07-11_01-23.json` + `batman_state.snapshot.json` |
| JWT | Valid — `data/access_token.json` saved **11-Jul 00:43 IST** (~23h left) |

**Current book** (`uat/deployed_positions/positions.json`, `source=cursor_chat`, expiry **21 Jul 2026**):

| Leg | Strike | Type | Side | Lots | Avg |
|-----|--------|------|------|------|-----|
| pe_sell | 24150 | PE | SELL | 2 | 146.60 |
| pe_buy | 24100 | PE | BUY | 1 | 128.50 |
| ce_buy | 24250 | CE | BUY | 1 | 174.35 |
| ce_sell | 24350 | CE | SELL | 2 | 128.15 |

Screenshot: `uat/deployed_positions/sensibull_chat_latest.png`

**Register evidence** (`data/uat/deployments/deploy_log.jsonl`):

- `wizard_started` 01:22 IST
- `confirmed` 01:23 IST → `batman_2026-07-11_01-23.json`
- Log: `UAT register: using cursor_chat positions.json (skip OCR)`

### 25.4 End state (session close 2026-07-11 ~01:52 IST)

| Bot | Status |
|-----|--------|
| DRISHTI | **RUNNING** (lock OK) |
| KAVACH | **RUNNING** (lock OK) — ShadowBroker 4 legs; ATO restore validated |
| JAGRAN | **RUNNING** |
| SARANSH | **RUNNING** |

| Check | Result |
|-------|--------|
| `scripts/phase1_bot_check.py` | **PASS** (all 4 bots, Telegram send OK) |
| `scripts/quick_uat_positions_gate.py` | **PASS** (~13–18s) when run for book validation |
| NIFTY LTP cache | **Stale** off-hours — expected; DRISHTI refreshes at market open |

### 25.5 Logs (UAT mode — 2026-07-11)

```
Desktop/Batman Executed Data/Logs/uat/runtime/2026-07/2026-07-11/kavach/logs/all.log
Desktop/Batman Executed Data/Logs/uat/runtime/2026-07/2026-07-11/kavach/errors/all_errors.log
```

| Time | Level | Meaning |
|------|-------|---------|
| 00:45 IST | ERROR ×4 | Tuple `startswith` during Batman Complete auto-register — **fixed in code** |
| 01:23 IST | WARNING | Session bundle `workspace_root` arity — **fixed in code** |
| 01:23+ IST | — | **No new errors** after successful Register |
| 01:34 IST | INFO | Clean KAVACH restart: ATO restore, armed 09:25 |

**Known non-fatal off-hours:** stale NIFTY cache; KAVACH ATO startup scan may warn — monitoring continues.

### 25.6 Next session — copy-paste prompts

**New book (bots RUNNING):**

```
@FAST_UAT_PROMPT.md @uat-sensibull-from-chat

FAST UAT — update book only. Execute yourself. No bot restart.
1. Read screenshot → write positions.json (cursor_chat, leg order pe_sell/pe_buy/ce_buy/ce_sell)
2. Save as uat/deployed_positions/sensibull_chat_latest.png
3. Run: .venv\Scripts\python.exe scripts\quick_uat_positions_gate.py
4. Reply OK + expiry + legs table + "Tap Register in KAVACH now"
Do NOT stop/start bots. Do NOT run daily test suite unless FULL UAT.
```

**Market open / health check:**

```
Read NEW_CHAT_HANDOFF.md, CONTEXT.md §25, AGENTS.md.
Confirm all 4 bots RUNNING + nifty_ltp_cache.json feed_healthy age<90s.
If new screenshot → FAST UAT prompt. If code changed → FULL UAT + run_uat_e2e_verification.py.
```

**Voice one-liner:** *FAST UAT screenshot. No restart. quick_uat_positions_gate. Tap Register when OK.*

### 25.7 Key paths (quick reference)

Runtime lives on Desktop (not in git) — see `docs/MULTI_DEV_SETUP.md`.

| Artifact | Path |
|----------|------|
| Positions book | `Desktop/Batman Executed Data/Data and Reports/data/uat/deployed_positions/positions.json` |
| Screenshot | `Desktop/Batman Executed Data/Data and Reports/data/uat/deployed_positions/sensibull_chat_latest.png` |
| UAT state | `Desktop/Batman Executed Data/Data and Reports/data/uat/batman_state.json` |
| Active deployment | `Desktop/Batman Executed Data/Data and Reports/data/uat/deployments/batman_2026-07-11_01-23.json` |
| Session bundle | `Desktop/Batman Executed Data/Data and Reports/data/uat/session_bundle/` |
| JWT | `Desktop/Batman Executed Data/Data and Reports/data/shared/access_token.json` |
| NIFTY cache | `Desktop/Batman Executed Data/Data and Reports/data/shared/nifty_ltp_cache.json` |
| UAT logs | `Desktop/Batman Executed Data/Logs/uat/runtime/YYYY-MM/YYYY-MM-DD/` |

## 26. Chromebook Linux + KAVACH Quick Tune (2026-07-15 night close)

**Resume file:** `NEW_CHAT_HANDOFF.md` (authoritative for next chat).

### Done this session
- Ported DEV to Debian 13 / Python 3.13 (Linux `.sh`, process control, local_runtime).
- Telegram tokens from Share folder; chat ID `5143751536` for all four bots.
- FAST UAT book: 21 Jul 2026 iron condor (`cursor_chat`) — gate PASS.
- **KAVACH Q79–Q98 locked** (Q86/Q88 skipped) → operator rules §14b + design pack.
- **ATO Configuration / Quick Tune coded** — buffers-only (`ato_configuration_wizard.py`).
- KAVACH restart verified: RUNNING · `phase1_bot_check` PASS · ConversationHandler loaded.
- Unit tests: `tests/test_ato_configuration_wizard.py` PASS.

### Operator next
1. Live Telegram try: **ATO Configuration** / `/ato_tune` (needs armed deployment).
2. Confirm Register for 21 Jul book if not done.
3. Remaining Phase 1 Q&A: **SARANSH OQ-SAR-REV-01…25** (5 at a time).

### Say to Agent
> Read NEW_CHAT_HANDOFF.md first (2026-07-15 night resume). Continue from Quick Tune coded.
