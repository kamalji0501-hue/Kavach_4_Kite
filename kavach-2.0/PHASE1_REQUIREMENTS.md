# Batman v3 — Phase 1 User Requirements (Captured)

Last updated: 2026-06-05 (four-bot scope + UAT primary — OQ-P1 batch 1)  
Owner: Rahul  
Captured by: Architecture discovery session (Day 1)

> **Purpose:** Plain-English requirements from the operator. Engineering maps these to code — operator does not choose Python modules/files.
>
> **Phase 1 Telegram bots (locked 2026-06-05):** DRISHTI, KAVACH, JAGRAN, **SARANSH** (4th — optional startup if token missing).
>
> **Rollout plan:** `PHASE1_IMPLEMENTATION_PLAN.md` (7 gates, step by step)  
> **Open items:** `PHASE1_OPEN_QUESTIONS.md`

---

## 0. Gradual rollout sequence (LOCKED 2026-05-29)

Move forward **slowly, one gate at a time**. Do not skip until current gate has pass/fail evidence in the daily log.

| Step | Gate | What we prove |
|------|------|---------------|
| **1** | **NIFTY LTP** | Fetch live NIFTY LTP consistently (Dhan websocket) |
| **2** | **Telegram bots** | DRISHTI, KAVACH, JAGRAN, SARANSH working over Telegram |
| **3** | **Dhan positions** | Fetch open positions via API; assess reliability |
| **4** | **KAVACH configured** | Register wizard, weekly storage, daily scheduler, settings |
| **5** | **ATO / choppy market** | User-triggered or volatile market — settings behave correctly (simulated orders) |
| **6** | **Performance** | Review speed, stability, config tuning |
| **7** | **JAGRAN** | Errors from all testing surface correctly; learn failure patterns |

**Current step:** Gate 1 (NIFTY LTP) — next working session.

---

## 1. Phase 1 Scope Lock

### In scope (Telegram bots)

| Bot | Role |
|-----|------|
| **DRISHTI** | Token delivery, broker/market connectivity, infrastructure health |
| **KAVACH** | Register weekly Batman positions, ATO protect buy/sell, pause/resume, batman_complete |
| **JAGRAN** | Critical alerts — API failures, runtime errors, broker issues |
| **SARANSH** | Reporting — ATO cycles, point impact, daily/EOD summary, XLSX (see `telegram/design/saransh_design.md`) |

### Gate 5 evidence (locked OQ-P1-10, OQ-P1-23)

All **four** bots must be **RUNNING**: DRISHTI, KAVACH, JAGRAN, SARANSH before Gate 5 sign-off.

**UAT positions (OQ-P1-23):** Gate 5 uses **shadow broker / Sensibull screenshot book only** — no live Dhan position read required on laptop.

### JAGRAN severity (locked OQ-P1-06)

Stale NIFTY LTP cache from DRISHTI → JAGRAN **warning** (not critical). KAVACH order failures remain critical.

### Telegram chat tiers (locked OQ-P1-02)

| Tier | Bots | Telegram group |
|------|------|----------------|
| **Critical** | DRISHTI, KAVACH, JAGRAN | **Batman Alerts** (JAGRAN fan-in) |
| **Non-critical** | SARANSH | **Non Critical Alerts** (reports only; no JAGRAN routing) |

### Primary laptop mode (locked OQ-P1-03)

**UAT** is the default daily mode: `config/batman_mode.json` → `uat`, `data/uat/`, ShadowBroker, Sensibull `positions.json`. DRISHTI still provides JWT + NIFTY cache.

### Out of scope — comment out or disable (preserve code where noted)

| Item | Decision |
|------|----------|
| LAKSHMI | Comment out startup — revisit in ~3–4 months |
| SANCHALAK | Not Phase 1 |
| RATRIPAL, PRABHAT MUKTI, break-even wizard | Out of scope |
| Profit trailing | Off permanently (Phase 1) |
| Overnight hedge | Off permanently (Phase 1) |
| **Emergency watchdog** (auto flatten on loss) | **Remove — out of scope** |
| **KAVACH `/exit`** (close all positions) | **Remove — out of scope** |
| **Position monitor** (background position watcher) | **Off — not needed; logic is NIFTY LTP only** |
| Any algo-driven **position exit on expiry** | **No — operator exits manually on Dhan** |

### Operator communication rule

Use **bot names and trading scenarios** in questions — not Python file names.

### Dev vs production rollout

| Phase | Environment |
|-------|-------------|
| **Now** | Personal laptop dev — **simulated orders only** (nothing sent to Dhan); read **live** positions from Dhan API; NIFTY LTP via **websocket** (~1s); dynamic IP laptop cannot place live orders anyway |
| **Later** | VPS production (static IP) — only after dev environment is stable |

### Dev order mode (LOCKED)

- ATO buy/sell logic **runs** (breach/retrace decisions, logging, KAVACH notifications).
- **No real orders** placed to Dhan on laptop dev.
- Read **live positions** from Dhan API using operator-provided JWT (read-only).
- **Skip Flask simulator** for Phase 1 dev — test directly against **Dhan websocket** + API on laptop.
- Operator will share Dhan API/websocket documentation (folder/link — pending).

---

## 5b. Crash & recovery (LOCKED)

| Event | Behavior |
|-------|----------|
| Process crash / fatal runtime error | **Report to JAGRAN** (before exit) |
| After crash | **HALT** — process **exits** (no infinite restart loop — OQ-P1-04 **B**) |
| Recovery | Operator restarts bot via **Start Bots** `.bat`; then `/resume` or daily **Yes** before ATO runs again |

---

## 5c. Gap up / gap down at open (LOCKED)

- **No special gap-only logic** beyond normal ATO breach rules.
- Operator **manually handles** gap scenarios before/alongside algo.
- ATO runs from **09:25 IST** using standard NIFTY LTP vs sell-strike logic already built.

---

## 2. Weekly registration model (LOCKED)

### One registration per Batman week

1. Operator deploys iron condor **manually on Dhan** (once per weekly cycle).
2. Operator runs KAVACH **`/register` once** — selects 4 legs, confirms.
3. KAVACH stores strikes/qty/symbols in project deployment storage (persists for the **full week** until batman_complete).
4. **Next trading days:** operator does **NOT** re-register legs.
5. Each day (details in §3 — one scheduling question still open in `PHASE1_OPEN_QUESTIONS.md` PQ-01), system references the **same registered positions** and asks whether to run ATO protection for **today**.

### Day 1 — first Confirm after `/register`

- ATO protection starts **immediately** after Confirm (including startup scan).
- Broker legs must match wizard selection or Confirm **fails**.

### Re-register mid-week

- Warn: positions already registered — show current legs.
- Operator must **cancel** current registration first.
- **Full cleanup** of all algo state before new `/register`.
- Pause/resume: pause = full stop; resume = evaluate from **current NIFTY LTP**.

---

## 3. Daily scheduler — LOCKED (2026-05-29 session 3)

### Weekly + daily model

| When | Behavior |
|------|----------|
| **Registration day** (`/register` + Confirm) | ATO protection starts **immediately** after Confirm (startup scan included). |
| **Each subsequent trading day (prod/dev)** | At **09:25 IST** (config), KAVACH asks: *"Do you want to run ATO protection today?"* |
| **UAT mode (locked OQ-P1-08)** | **No daily 09:25 prompt** — operator starts ATO via **manual resume** / register confirm; no nag |
| **Operator taps Yes** | Run KAVACH ATO monitoring for **that day only**. |
| **Operator taps No** | Do **not** run ATO that day. Positions remain unchanged. |
| **Operator does not reply** | **Do not run** ATO that day. **Do not** keep re-asking. |

> **Note:** Prod/dev retains daily Yes/No gate. **UAT skips** the daily prompt (OQ-P1-08 **B**).

### Registration day vs next-morning prompt

- If operator already registered and started ATO **today**, **skip** the next-morning duplicate "run today?" prompt for that same calendar day.

### Configurable schedule times (must live in config file)

| Setting | Phase 1 value | Meaning |
|---------|---------------|---------|
| Daily prompt / algo start time | **09:25 IST** | When "run ATO today?" is sent |
| Algo end time | **15:15 IST** | When intraday ATO monitoring stops for the day |

Operator must be able to change these in config without code edits.

### AlgoScheduler

- Wire daily prompt + day-scoped ATO start/stop using the times above.
- Positions stay registered for the full week until `batman_complete`.

---

## 4. Register wizard — Phase 1 (LOCKED)

### Principle

**Do not strip existing KAVACH wizard behavior.** Defaults apply, but operator can still choose entry buffer, retrace, and poll interval as the current wizard already asks.

### Keep (existing functionality)

1. Select 4 legs from broker positions (PE BUY → PE SELL → CE BUY → CE SELL)
2. **Entry buffer** prompt (default **0** — operator can change)
3. **Retrace / exit buffer** prompt(s) as already built in KAVACH (default **5** — operator can change; separate CE/PE if wizard already supports it)
4. **Poll interval** prompt (default **1 second**)
5. Confirm summary

### Remove from wizard (Phase 1 only)

- Break-even step (RATRIPAL — future phase)
- Working-day / holiday marking step (RATRIPAL — future phase)

### Confirm behavior

- Allow Confirm outside market hours with **warning**.
- Success message in **KAVACH only** (no JAGRAN on normal arm).
- Fail Confirm if broker legs ≠ selected legs.

### ATO strategy defaults (LOCKED)

| Parameter | Value |
|-----------|-------|
| Entry buffer | 0 |
| Retrace | 5 |
| Poll interval | 1s |
| Max cycles | Unlimited |
| Sides | Both CE + PE always |
| Protect distance | 50 pts from sell strike |

---

## 5. Pause, resume, complete (LOCKED)

### Pause

- KAVACH stops **all** ATO monitoring and order placement.
- No new protect buys or sells.
- Existing protect legs **stay open** on Dhan.
- Read-only commands OK (status, legs, funds).
- Commands that would trade → error: *algo paused*.

### Resume

- Restart monitoring from **current NIFTY LTP**.

### batman_complete

- Operator signal: *"This Batman cycle is done from algo perspective."*
- **Does NOT** close or change Dhan positions.
- **Stops** ATO monitoring; **full state cleanup** for next `/register`.
- Operator handles actual position exit **manually on Dhan** (any day, including expiry).

### Exit features — REMOVED (Phase 1)

- No KAVACH `/exit`.
- No automated emergency flatten.
- **When implementing:** delete or fully disable exit-related code paths (operator approved removal, not just config off).

---

## 6. DRISHTI — infrastructure monitoring (LOCKED)

| Setting | Phase 1 value |
|---------|---------------|
| Broker / NIFTY health check interval | **Every 1 minute** during market hours |
| Fleet display | Show only **DRISHTI, KAVACH, JAGRAN, ATO monitoring status** |

### NIFTY LTP feed (LOCKED — single source of truth)

**Policy:** `NIFTY_LTP_POLICY.md`

- **Only DRISHTI** collects NIFTY LTP (in-process WebSocket default, REST poller optional).
- **All other bots** (KAVACH, ATO, etc.) read `data/nifty_ltp_cache.json` only — **never call Dhan for spot**.
- Primary: DRISHTI WebSocket in-process; REST poll every **2s** as configured fallback.
- Runtime backup: in-process WebSocket → REST failover when WS fails (session lock; config stays `websocket`).
- Auth: **client_id + access_token (JWT)** via DRISHTI TokenStore.
- NIFTY instrument: **IDX_I, security_id=13** (Dhan v2).
- Stale/missing cache → auto-pause ATO + JAGRAN (no broker fallback on trading path).
- Official docs: https://dhanhq.co/docs/v2/

---

## 7. JAGRAN — alerting (LOCKED)

- **Separate Telegram chat** from KAVACH (credentials in `telegram/bots/jagran/token.env`).
- Implemented via **incident publisher** (not a separate polling bot app) — see `JAGRAN_ERROR_MATRIX.md`.
- **Dual publish:** source bot chat (DRISHTI or KAVACH) **plus** JAGRAN for allowlisted critical incidents.
- Dedup, recovery messages, and incident ledger already coded in `bat_telegram/incident_publisher.py`.
- Phase 1 seed scenarios include: DRISHTI LTP/broker/token failures, KAVACH order rejection/margin failures, websocket retry exhaustion (≥5 retries → JAGRAN).
- **Normal ATO buy/sell success** → notify **KAVACH only**, not JAGRAN.
- Add **`/recent`** command on JAGRAN to view recent incidents (Phase 1).
- Stale-feed thresholds and GIFT token validation: **engineering derives from Dhan docs** when operator shares link (EQ-01, EQ-02).

---

## 8. What KAVACH is allowed to do on Dhan (Phase 1)

| Action | Allowed? |
|--------|----------|
| BUY ATO protect leg (50 pts from sell strike) on breach | **Yes** |
| SELL ATO protect leg on retrace | **Yes** |
| Close iron condor legs | **No — manual on Dhan** |
| Close all positions / emergency exit | **No — feature removed** |

---

## 9. Engineering gap list (not implemented yet)

| Requirement | Current gap |
|-------------|-------------|
| ATO starts on Confirm | Confirm saves state; monitoring thread may not start |
| Weekly persistence | Deployment file exists; daily scheduler not wired |
| Pause = full stop | Pause may be flag-only |
| Wizard defaults (retrace 5, poll 1s) | Code still defaults retrace 20 in places |
| Remove exit features | `/exit` and emergency module still in codebase |
| LAKSHMI off | Still started in main process |
| Position monitor off | Still in always-on list |
| Simplified wizard | Break-even + calendar steps still present |
| Dhan websocket LTP | REST poll today; **websocket integration required** |
| Daily 09:25 prompt + 15:15 end | Not wired; times not in config yet |
| Simulated orders on dev | Mock guard exists but needs explicit dev/simulate mode |
| DRISHTI 1-min health | Default interval may still be 3600s in params |

---

## 10. Related files

| File | Purpose |
|------|---------|
| `PHASE1_OPEN_QUESTIONS.md` | Unresolved questions only |
| `PHASE1_DHAN_INTEGRATION.md` | Dhan websocket/LTP integration notes + reference code |
| `CONTEXT.md` | Project context; points here for Phase 1 |
| `OPEN_QUESTIONS.md` | Original project-wide open questions |
| `Dhan/Fetch LTP Working Code 09 Apr 26/...` | Operator's working NIFTY LTP websocket reference |

---

*Update this file when operator answers items in PHASE1_OPEN_QUESTIONS.md.*
