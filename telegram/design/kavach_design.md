# KAVACH (कवच) — Detailed Design
## Bot 2 | Core Positions, ATO Protection, Deployment Wizard
## Design Doc | Locked: 2026-04-04 | Updated: 2026-06-20 | Status: DESIGN COMPLETE — operator rules extended

> **Operator / trading rules (2026-06-20):** **`docs/KAVACH_ATO_OPERATOR_RULES.md`** is authoritative for ATO behaviour, register gate, manual legs, economy testing.  
> **Superseded below:** Step 0 “Yes — start wizard while armed” → now **Batman Complete required first**. ATO strike auto-only → now **custom lots + custom strike + presets**.

---

## Architecture Decision — LOCKED 2026-04-04

> **`telegram/bots/kavach/` is the ONE authoritative system. `bot/` (old handlers) is RETIRED.**

|                 | Old system (`bot/handlers/`)                | New system (`telegram/bots/kavach/`)        |
| --------------- | ------------------------------------------- | ------------------------------------------- |
| Status          | **RETIRED** — reference only, do not extend | **AUTHORITATIVE** — all new code goes here  |
| Deploy command  | `/choose` (toggle-based)                    | `/deploy` (ConversationHandler, 4 steps)    |
| Deployment data | Written to `state.json`                     | Written to `data/deployments/batman_*.json` |
| ATO reads from  | `state.get("positions.ce_sell")`            | deployment file (`batman_*.json`)           |
| Armed signal    | `deployment.confirmed = True` in state      | file presence in `data/deployments/`        |

**What this means for code:**
- Old `bot/` code logic and components (auth, resilience, broker adapter, event patterns) are REUSABLE as reference — import them or copy patterns, do not extend them
- `bot/handlers/` will not gain new features — only `telegram/bots/kavach/` grows
- Rahul manually deploys Batman on the Dhan app. KAVACH reads what is already deployed. KAVACH does NOT place the initial iron condor — that responsibility (batman_entry module) is fully manual/user

---

## Role

KAVACH is the **trading operations bot**. It handles:
1. The `/deploy` wizard — Rahul selects the 4 Batman legs he already placed on Dhan, KAVACH registers them and arms the algo
2. ATO monitoring notifications — alerts when ATO fires or retraces
3. Trading control commands — pause/resume algo, emergency exit, mark deployment complete

Rahul deploys Batman positions himself on the Dhan app. KAVACH's job is to know *which* positions are Batman's, protect them with ATO logic, and give Rahul full control via Telegram commands.

> **Process model (LOCKED 2026-04-04):** KAVACH runs as an asyncio task inside a single `python main.py` process on the VPS. It shares the same `BatmanBroker`, `StateManager`, and `EventBus` instances as all algo modules — no IPC needed. Rahul controls everything from mobile via Telegram; he never needs shell access once the server is running.

> **`/pnl` is NOT in KAVACH.** P&L reporting belongs exclusively to LAKSHMI. KAVACH owns trading commands only.

---

## Core Responsibilities

| #   | Responsibility                                                                                 | When active                              |
| --- | ---------------------------------------------------------------------------------------------- | ---------------------------------------- |
| 1   | **Deployment Wizard** — interactive 4-leg selection, ATO auto-calc, confirmation, file write   | On `/deploy` command                     |
| 2   | **Batman Complete** — full cleanup: stop monitoring, archive deployment file, reset algo fresh | On `/batman_complete` command            |
| 3   | **ATO status** — report current ATO state per side (triggered/idle, cycle counts)              | On `/ato` command                        |
| 4   | **Emergency exit** — close all positions immediately at market                                 | On `/exit` command (yes/no confirmation) |
| 5   | **Algo control** — pause/resume the ATO monitoring loop                                        | On `/pause`, `/resume`                   |
| 6   | **Trade event notifications** — ATO triggered, ATO retrace exit, deploy confirmed, limits hit  | Proactive — quiet hours apply            |

---

## Command Reference (Updated — 2026-04-04)

| Command            | Confirm Required               | Purpose                                                                                   | Status                                   |
| ------------------ | ------------------------------ | ----------------------------------------------------------------------------------------- | ---------------------------------------- |
| `/deploy`          | No (wizard has its own ✅ flow) | Start deployment wizard — 4-leg selection + ATO calc + arm Batman                         | **NEW**                                  |
| `/batman_complete` | Yes (inline keyboard)          | Batman positions closed — stop modules, archive file, clear state, reset algo fresh       | **RENAMED + ENHANCED**                   |
| `/batman_done`     | —                              | **Alias** for `/batman_complete` — backward compat                                        | Alias                                    |
| `/ato`             | No                             | Show current ATO state (triggered/idle per side, cycle counts)                            | Existing                                 |
| `/exit`            | Yes (inline keyboard, 30s)     | Emergency exit — close all positions at market, archive file, put algo in safe idle state | Existing + Enhanced                      |
| `/pause`           | No                             | Pause ATO monitoring loop (was `/stop_algo`)                                              | Renamed                                  |
| `/resume`          | No                             | Resume ATO monitoring loop (was `/resume_algo`)                                           | Renamed                                  |
| `/start_now`       | No                             | Force-start algo immediately (was `/force_algo`)                                          | Renamed                                  |
| `/legs`            | No                             | Show current Batman open legs (was `/positions`)                                          | Renamed                                  |
| `/funds`           | No                             | Show available margin/funds (was `/balance`)                                              | Renamed                                  |
| `/status`          | No                             | System & module status                                                                    | Existing                                 |
| `/stop_algo`       | —                              | Alias for `/pause` — backward compat                                                      | Alias                                    |
| `/resume_algo`     | —                              | Alias for `/resume` — backward compat                                                     | Alias                                    |
| `/confirm_deploy`  | —                              | **RETIRED** — replaced by `/deploy`                                                       | Retired, alias `/choose` kept for compat |

---

## Deployment Day Flexibility (Confirmed — 2026-04-04)

Batman is typically deployed on Wednesday (4DTE) but may also be deployed on Thursday (3DTE) or Friday (2DTE) based on market conditions and volatility. **The entire algo pipeline is day-agnostic — no weekday restriction exists anywhere in the critical path.**

| Path                                     | Gating condition              | Weekday check?                                         |
| ---------------------------------------- | ----------------------------- | ------------------------------------------------------ |
| ATO monitoring start                     | `deployment.confirmed` flag   | **None**                                               |
| AlgoScheduler daily time-picker prompt   | `deployment.confirmed` flag   | **None**                                               |
| AlgoScheduler auto-start / EOD auto-stop | Time of day only              | **None**                                               |
| `/deploy` wizard itself                  | No preconditions              | **None**                                               |
| EOD “batman complete?” reminder prompt   | After EOD, any day, if active | **None** — fires any day (Tuesday restriction removed) |

**`/deploy` works identically on any DTE (4DTE, 3DTE, 2DTE, or even 0DTE if needed).**
The algo monitors whatever has been deployed — it does not care when it was deployed.

**Deployment for any expiry:** Rahul may deploy for the 7 Apr expiry, then close it on 6 Apr and immediately deploy for 13 Apr. The algo handles this by:
1. Rahul closes 7 Apr positions on Dhan manually
2. Rahul sends `/batman_complete` → KAVACH: full cleanup → algo fresh, deployment file archived
3. Rahul deploys new 13 Apr positions on Dhan
4. Rahul sends `/deploy` → new legs selected, ATO armed, monitoring begins
5. AlgoScheduler starts algo next morning (or use `/start_now` for immediate start)

---

## Deployment Wizard (`/deploy`) — Full Step-by-Step

**Trigger:** Rahul sends `/deploy` to KAVACH bot. Can be used on any trading day.

### Step 0 — Pre-archive safety check (BEFORE any archive happens)

```
If data/deployments/ contains an existing batman_*.json file:
  KAVACH sends a warning message:
    "⚠️ Batman is currently ARMED (deployment file exists).
     Running /deploy will pause ATO monitoring during the wizard.
     If you cancel mid-wizard, Batman will NOT be re-armed automatically.
     Continue?"
  [Yes, continue — start wizard]  [❌ Cancel — keep current deployment]

  → If Cancel: wizard aborts. Existing deployment file untouched. Algo continues.
  → If Yes (or no file exists): proceed to archive step below.

Archive step:
  1. Scan data/deployments/ for all existing *.json files
  2. Move all found files to data/deployments/archive/
  3. Append archive event to data/deployments/deploy_log.jsonl
  4. Create archive/ folder if it does not exist yet
  5. Proceed to Step 1 only after archive is complete
```

This ensures exactly **one active deployment file** exists at all times. No date logic required.
If `/deploy` is cancelled after this point → no `.json` file written → algo enters WAIT state (safe).

### Step 1 — Fetch & Filter open positions from broker

```
1. Call broker API: get all open positions
2. Filter: NIFTY options ONLY (see Position Filter Rules below)
3. Sort: by strike price ascending (lowest PE first, highest CE last)
4. Build InlineKeyboardMarkup — each button shows:
     [NIFTY25APR24200PE | LONG 650 | avg: ₹45.20]
     [NIFTY25APR24000PE | SHORT 1300 | avg: ₹28.50]    ← direction explicit
5. Send to user:
     "Step 1/4 — Select your PE BUY leg:"
     [list of buttons, one per position]
     [❌ Cancel]
```

### Step 2 — PE SELL selection

```
1. User taps a button → KAVACH records pe_buy (symbol, strike, qty, avg_price, instrument_token, expiry)
2. Remove pe_buy from available options (cannot be selected again)
3. Send updated list with remaining positions only:
     "Step 2/4 — Select your PE SELL leg:
      ✅ PE BUY: NIFTY25APR24200PE (LONG 650)"
     [buttons — pe_buy row is GONE from this list]
     [❌ Cancel]
```

### Step 3 — CE SELL selection

```
Same pattern. Remaining positions = original list − pe_buy − pe_sell.
PE BUY ✅ and PE SELL ✅ both shown in header.
"Step 3/4 — Select your CE SELL leg:
 ✅ PE BUY: NIFTY25APR24200PE | ✅ PE SELL: NIFTY25APR24000PE"
[buttons — already-selected rows are GONE]
[❌ Cancel]
```

### Step 4 — CE BUY selection

```
Same pattern. Remaining positions = original list − pe_buy − pe_sell − ce_sell.
All 3 prior selections shown in header.
"Step 4/4 — Select your CE BUY leg:
 ✅ PE BUY | ✅ PE SELL | ✅ CE SELL"
[buttons — only un-selected positions shown]
[❌ Cancel]
```

### Step 5 — Summary & ATO auto-calculation

```
Auto-calculate ATO strikes:
  pe_ato_strike = pe_sell_strike − ato_step      (default ato_step = 50, from params.json)
  ce_ato_strike = ce_sell_strike + ato_step
  pe_ato_symbol = NIFTY option symbol at pe_ato_strike, same expiry as pe_sell, PE type
  ce_ato_symbol = NIFTY option symbol at ce_ato_strike, same expiry as ce_sell, CE type

Send summary message:

  🦇 Batman Position Summary

  PE BUY  : NIFTY25APR24200PE  qty=650   avg=₹45.20
  PE SELL : NIFTY25APR24000PE  qty=1300  avg=₹28.50
  CE SELL : NIFTY25APR24800CE  qty=1300  avg=₹31.10
  CE BUY  : NIFTY25APR25000CE  qty=650   avg=₹18.75

  In case of range breach, I will trigger:
  🛡 PE ATO : NIFTY25APR23950PE  (strike 23950 = 24000 − 50)
  🛡 CE ATO : NIFTY25APR24850CE  (strike 24850 = 24800 + 50)

  [✅ Confirm & Arm Batman]   [❌ Cancel & Start Over]
```

### Step 6 — Final confirmation

```
ON ✅ CONFIRM:
  1. Write data/deployments/batman_YYYY-MM-DD_HH-MM.json  (full schema below)
  2. Append confirmed event to data/deployments/deploy_log.jsonl
  3. Reply:
       "✅ Batman armed. KAVACH is watching.
        File: batman_2026-04-04_10-23.json
        PE ATO fires when NIFTY ≤ 24000 | CE ATO fires when NIFTY ≥ 24800"

ON ❌ CANCEL (at any step):
  1. Zero file writes (archive already moved — no active JSON file exists now)
  2. Append wizard_cancelled event to deploy_log.jsonl
  3. Reply:
       "❌ Deployment cancelled. No file written. Run /deploy again when ready."

ON TIMEOUT (user idle > timeout_seconds = 120s at any step):
  Same as cancel. Log event: wizard_timeout.
```

---

## Position Filter Rules (NIFTY-only — enforced in Step 1)

| Keep                           | Reject                                    |
| ------------------------------ | ----------------------------------------- |
| NIFTY weekly options (CE, PE)  | SENSEX options                            |
| NIFTY monthly options (CE, PE) | BANKNIFTY options                         |
| Any expiry Rahul has deployed  | Equity / MF positions                     |
| Any strike price, any qty      | Futures (NIFTY FUT)                       |
|                                | Any instrument whose underlying ≠ "NIFTY" |

Filtering logic: symbol starts with `"NIFTY"` AND option type is CE or PE.
Exact field names depend on Dhan API position response — handled in broker `get_open_positions()` method.

**No ratio validation.** Rahul's confirmation is sufficient authority. If CE sell qty ≠ 2 × CE buy qty, wizard proceeds without warning.

---

## ATO Strike Calculation (auto-only, never user-overridden)

```python
# Inputs: pe_sell_strike (e.g. 24000), ce_sell_strike (e.g. 24800)
ato_step       = params["deploy_wizard"]["ato_step"]   # default: 50

pe_ato_strike  = pe_sell_strike - ato_step             # 23950
ce_ato_strike  = ce_sell_strike + ato_step             # 24850

# Symbol construction uses same expiry as the selected sell leg
pe_ato_symbol  = construct_symbol("NIFTY", expiry, pe_ato_strike, "PE")
ce_ato_symbol  = construct_symbol("NIFTY", expiry, ce_ato_strike, "CE")
```

`ato_step` is configurable in `params.json → deploy_wizard.ato_step`. The user **cannot** override strikes interactively — the only action at the summary screen is Confirm or Cancel.

---

## Register Flow Extension — NIFTY LTP Poll Interval (Locked — 2026-05-04)

Objective:
Add one `/register` wizard question to control NIFTY LTP polling cadence and reduce broker throttling risk.

Telegram prompt:
"In how many seconds should I check NIFTY LTP for ATO monitoring?"

Allowed options (predefined buttons only):
1. 1 second
2. 2 seconds
3. 3 seconds
4. 4 seconds
5. 5 seconds
6. 10 seconds
7. 15 seconds

Input policy (locked):
1. User must select one option from Telegram keyboard buttons.
2. Manual typed input for seconds is not accepted in this step.
3. Wizard does not proceed until one valid option is selected.

Persistence contract:
1. Save selected value in deployment payload as `ato_poll_interval_seconds`.
2. ATO loop uses this per-deployment value.
3. Legacy deployment files without this field fallback to existing config default.

Final summary contract:
1. `/register` summary must display the selected poll interval.
2. Include a short note that polling interval is applied to protect against over-polling/throttling.

---

## Wizard State Machine

```
[User: /deploy]
      │
      ▼
[Step 0] Check if batman_*.json exists in data/deployments/
         IF YES: Send safety warning + Yes/No confirm before archiving
         IF NO:  Proceed directly to archive step (no files to move)
         Archive: move *.json → archive/, append archive_moved to log
      │
      ▼
[Step 1] Fetch NIFTY open positions from broker
         Filter: NIFTY options only | Sort: strike ascending
         Build: full position list (N buttons, direction explicit: LONG/SHORT)
         "Step 1/4 — Select your PE BUY leg:"
         [NIFTY...PE | LONG/SHORT qty | avg ₹]  ×N buttons
         [❌ Cancel]
      │  user taps a button
      ▼
[Step 2] Record pe_buy. Remove pe_buy from available list.
         Show ✅ pe_buy in header.
         "Step 2/4 — Select your PE SELL leg:"
         [N-1 buttons — pe_buy gone]   [❌ Cancel]
      │  user taps a button
      ▼
[Step 3] Record pe_sell. Remove pe_sell from available list.
         Show ✅ pe_buy + ✅ pe_sell in header.
         "Step 3/4 — Select your CE SELL leg:"
         [N-2 buttons — pe_buy + pe_sell gone]   [❌ Cancel]
      │  user taps a button
      ▼
[Step 4] Record ce_sell. Remove ce_sell from available list.
         Show ✅ pe_buy + ✅ pe_sell + ✅ ce_sell in header.
         "Step 4/4 — Select your CE BUY leg:"
         [N-3 buttons — only un-selected positions]   [❌ Cancel]
      │  user taps a button
      ▼
[Step 5] Record ce_buy.
         Auto-calculate: pe_ato_strike = pe_sell − 50, ce_ato_strike = ce_sell + 50
         Display full summary + calculated ATO strikes
         [✅ Confirm & Arm Batman]   [❌ Cancel & Start Over]
      │                                    │
      ▼                                    ▼
[CONFIRM]                          [CANCEL after archive]
Write batman_YYYY-MM-DD_HH-MM.json Zero file writes
Append confirmed to log            Append cancelled to log
Reply: "✅ Armed"                  Reply: "❌ Cancelled. ATO in WAIT state. Run /deploy again."


At ANY step: idle > 120s (timeout_seconds) → same as ❌ Cancel.
Log event: wizard_timeout.
```

---

## Deployment File Schema

`data/deployments/batman_YYYY-MM-DD_HH-MM.json`

```json
{
  "schema_version": 1,
  "deployed_date": "2026-04-04",
  "deployed_at": "2026-04-04T10:23:45+05:30",
  "confirmed_at": "2026-04-04T10:24:12+05:30",
  "expiry_weekday": 1,
  "_expiry_weekday_comment": "0=Mon 1=Tue 2=Wed 3=Thu 4=Fri. Used by profit_trailing to know which day to run.",
  "positions": {
    "pe_buy":  { "symbol": "NIFTY25APR24200PE", "strike": 24200, "expiry": "25APR", "qty": 650,  "avg_price": 45.20, "instrument_token": "..." },
    "pe_sell": { "symbol": "NIFTY25APR24000PE", "strike": 24000, "expiry": "25APR", "qty": 1300, "avg_price": 28.50, "instrument_token": "..." },
    "ce_sell": { "symbol": "NIFTY25APR24800CE", "strike": 24800, "expiry": "25APR", "qty": 1300, "avg_price": 31.10, "instrument_token": "..." },
    "ce_buy":  { "symbol": "NIFTY25APR25000CE", "strike": 25000, "expiry": "25APR", "qty": 650,  "avg_price": 18.75, "instrument_token": "..." }
  },
  "ato": {
    "pe_protect_symbol": "NIFTY25APR23950PE",
    "pe_protect_strike": 23950,
    "ce_protect_symbol": "NIFTY25APR24850CE",
    "ce_protect_strike": 24850,
    "ato_step": 50
  },
  "status": "armed"
}
```

**Field notes:**
- `instrument_token` — broker-specific token for fast order routing; captured from broker position response
- `expiry` — string in broker format (e.g. `"25APR"`) — used for ATO symbol construction
- `deployed_date` — ISO date the wizard was run (renamed from `week_start` — day-agnostic deployment, not necessarily week-aligned)
- `schema_version` — allows future schema migrations without breaking reads
- File naming: `batman_YYYY-MM-DD_HH-MM.json` — timestamp ensures uniqueness in archive

---

## Audit Log Schema

`data/deployments/deploy_log.jsonl` — **append-only**. One JSON object per line. Never rewritten or deleted.

```jsonl
{"ts": "2026-04-04T10:21:00+05:30", "event": "wizard_started", "by": "rahul"}
{"ts": "2026-04-04T10:21:01+05:30", "event": "archive_moved", "files": ["batman_2026-03-29_09-15.json"]}
{"ts": "2026-04-04T10:22:10+05:30", "event": "positions_selected", "pe_buy": "NIFTY25APR24200PE", "pe_sell": "NIFTY25APR24000PE", "ce_sell": "NIFTY25APR24800CE", "ce_buy": "NIFTY25APR25000CE"}
{"ts": "2026-04-04T10:24:12+05:30", "event": "confirmed", "file": "batman_2026-04-04_10-23.json"}
{"ts": "2026-04-07T11:00:00+05:30", "event": "batman_complete", "by": "rahul"}
{"ts": "2026-04-09T09:30:00+05:30", "event": "wizard_started", "by": "rahul"}
{"ts": "2026-04-09T09:30:01+05:30", "event": "archive_moved", "files": ["batman_2026-04-04_10-23.json"]}
{"ts": "2026-04-09T09:31:20+05:30", "event": "wizard_cancelled"}
```

**Events catalogue:**

| Event                 | When logged                                             |
| --------------------- | ------------------------------------------------------- |
| `wizard_started`      | Immediately when `/deploy` received                     |
| `archive_moved`       | After archive step completes (lists files moved)        |
| `positions_selected`  | When all 4 legs picked (before summary screen)          |
| `confirmed`           | After user taps ✅ and JSON file is written              |
| `wizard_cancelled`    | User tapped ❌ at any step                               |
| `wizard_timeout`      | User went idle > `timeout_seconds` at any step          |
| `batman_complete`     | After `/batman_complete` confirmed — full cleanup done  |
| `wizard_no_positions` | No NIFTY positions found at Step 1 — wizard exits early |

---

## `/batman_complete` — Batman Positions Complete (Full Cleanup)

## `/exit` — Emergency Exit (System Safe-Idle After Execution)

When Rahul sends `/exit`:

```
1. KAVACH sends inline-keyboard confirmation (30s timeout):
     "🚨 Emergency Exit?
      This will CLOSE ALL POSITIONS at market price immediately.
      This CANNOT be undone."
     [✅ Yes — Close all now]   [❌ Cancel]

2. ON ✅ YES:
     → All open positions closed at market via broker API
     → THEN: same full cleanup as /batman_complete:
         Algo modules stopped (ATO, trailing)
         Deployment file archived (data/deployments/ → archive/)
         Append emergency_exit event to deploy_log.jsonl
         All state cleared (positions, ATO strikes, flags)
         deployment.confirmed → False
     → ATO enters WAIT state (safe idle — nothing to monitor)
     → Reply: "🚨 Emergency Exit executed. All positions closed.
               Algo reset — deploy fresh via /deploy when ready."

3. ON ❌ CANCEL or timeout:
     → Nothing changes.
     → Reply: "Emergency exit cancelled. Positions unchanged."
```

**Why the same cleanup as `/batman_complete`:** After closing all positions, there is nothing for ATO to monitor. Leaving the deployment file in place would cause ATO to attempt breach monitoring for non-existent positions, which could trigger phantom orders. Archiving the file ensures ATO enters its safe WAIT state.

---

## `/batman_complete` — Batman Positions Complete (Full Cleanup)

When Rahul sends `/batman_complete` (or alias `/batman_done`) to KAVACH:

```
1. KAVACH sends inline-keyboard confirmation:
     "🦇 Batman Complete?
      This will:
      • Stop all algo modules (ATO, trailing)
      • Archive the deployment file (data/deployments/ → archive/)
      • Clear all state (positions, ATO strikes, order IDs, flags)
      • Reset algo — fresh, ready for next deployment
      Your positions on Dhan are NOT closed automatically."
     [✅ Yes — Batman complete]   [❌ Cancel]

2. ON ✅ YES:
     → Algo modules stopped immediately (ATO, profit_trailing)
     → Deployment file archived:
         Move data/deployments/batman_*.json → data/deployments/archive/
         (same mechanism as /deploy Step 0 archive)
     → Append batman_complete event to deploy_log.jsonl
     → All state cleared:
         positions.ce_sell/buy/pe_sell/buy → None
         ato.ce_protect_symbol/strike, pe_protect_symbol/strike → None
         ato.ce_triggered, pe_triggered, order IDs → False/None
         deployment.confirmed → False
         deployment.batman_complete → False  (ready for re-deploy)
         deployment.positions_confirmed_date → None
     → ATO module enters WAIT state (no file in active dir)
     → Reply: "✅ Batman Complete — Algo Reset.
               Deployment file archived. ATO is now idle.
               Deploy on Dhan, then run /deploy."

3. ON ❌ CANCEL:
     → Nothing changes. Algo continues running.
     → Reply: "Cancelled. Batman monitoring continues."
```

**Key design principle:** Cleanup is FULL and IMMEDIATE. After `/batman_complete`, the algo is in the exact same state as a fresh startup. The deployment file is archived so ATO's file-presence check correctly reports "not armed". No half-cleaned variables, no stale ATO strikes, no orphan deployment files.

**Re-deploy path after `/batman_complete` (mid-week or cross-expiry roll):**

```
1. Rahul closes existing positions manually on Dhan app (any time, any day)
2. Rahul sends /batman_complete → KAVACH: stops algo, archives file, clears state → algo fresh + idle
3. Rahul deploys new Batman positions on Dhan app (new expiry, new strikes, any day)
4. Rahul sends /deploy → wizard selects 4 new legs, ATO armed, monitoring begins
5. AlgoScheduler starts algo next morning (or use /start_now for immediate start)
```

Same-day roll example: close 7 Apr positions at 14:00 → `/batman_complete` → deploy 13 Apr at 14:15 → `/deploy` → algo starts 09:15 next trading day. No restrictions.

---

## Algo Integration — How `ato_protection.py` Reads the Deployment File

On module startup (`_run()` entry):

```
1. Scan data/deployments/ for batman_*.json
2. Exactly ONE file should exist if /deploy was completed:

   FILE FOUND:
     → Load JSON → extract these fields:
         positions.ce_sell.strike  → ce_sell_strike (breach threshold)
         positions.pe_sell.strike  → pe_sell_strike (breach threshold)
         ato.ce_protect_symbol     → symbol to BUY on CE breach
         ato.ce_protect_strike     → CE ATO strike
         ato.pe_protect_symbol     → symbol to BUY on PE breach
         ato.pe_protect_strike     → PE ATO strike
     → ATO module is ARMED — begin monitoring loop

   NO FILE FOUND:
     → Log warning: "No deployment file found. ATO blocked until /deploy is run."
     → Enter WAIT state — poll for file appearance every 30s
     → Does NOT crash — stays alive
     → On file appearance: load + arm immediately, no restart needed

3. Hot-reload: on each ATO monitoring tick, check file mtime.
   If mtime changed (new /deploy run) → reload file immediately.
```

**Fields this replaces** (previously hardcoded or stored in state):
- `ce_protect_symbol`, `pe_protect_symbol` — exact option symbol for ATO order
- `ce_protect_strike`, `pe_protect_strike` — strike price used for breach detection
- `ce_sell_strike`, `pe_sell_strike` — the sell leg strike (ATO fires when spot crosses this)

---

## `params.json` Reference (KAVACH)

See `telegram/bots/kavach/params.json` for the full current file.

| Group           | What it controls                                           | Key values (defaults)                                 |
| --------------- | ---------------------------------------------------------- | ----------------------------------------------------- |
| `quiet_hours`   | Proactive notifications suppressed outside this window     | `08:00` – `23:30` IST. Commands work 24/7.            |
| `commands`      | Toggle individual bot commands on/off without restart      | All enabled by default                                |
| `confirmations` | Which commands require yes/no reply before executing       | `emergency_exit`, `batman_complete` (inline keyboard) |
| `notifications` | Which trade events KAVACH announces via Telegram           | ATO trigger/exit, deploy, batman_complete, algo       |
| `deploy_wizard` | Wizard settings — ATO step, timeout, filter, storage paths | `ato_step: 50`, `timeout_seconds: 120`                |
| `retry`         | Retry config for broker API calls                          | 3 attempts, 2s delay, ×1.5 backoff                    |
| `rate_limit`    | Protect against accidental command spamming                | 10 commands/min, 5s cooldown                          |

---

## Files to Create (Coding Phase)

| File                                    | Purpose                                                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `telegram/bots/kavach/deploy_wizard.py` | ConversationHandler — 4 states (SELECT_PE_BUY, SELECT_PE_SELL, SELECT_CE_SELL, SELECT_CE_BUY) + CONFIRM state |
| `telegram/bots/kavach/bot.py`           | KAVACH async entry point — registers /deploy, /batman_complete, /ato, /exit, /pause, /resume, /start_now      |
| `data/deployments/.gitkeep`             | Ensure active folder exists in git                                                                            |
| `data/deployments/archive/.gitkeep`     | Ensure archive folder exists in git                                                                           |
| `modules/ato_protection.py`             | Update: read deployment file instead of state/hardcoded values                                                |

---

## Pre-Coding Technical Notes

> These are the answers to "how exactly does the code know X?" — verified from existing source. Read before writing any code.

### 1. Broker Position Fields (from `core/broker.py` → `get_positions()`)

`get_positions()` already exists and returns a Pandas DataFrame. Field names confirmed from `close_all_positions()` implementation in broker.py:

```python
# Exact column names in the DataFrame returned by get_positions():
row["tradingSymbol"]   # or row["tradingsymbol"]  — the full option symbol e.g. "NIFTY25APR24200PE"
row["netQty"]          # net quantity (positive = long, negative = short)
row["buyQty"]          # total buy qty
row["sellQty"]         # total sell qty
row["avgPrice"]        # average price — field name needs live verification (may be "buyAvg" / "sellAvg")
```

**Wizard must use:** `tradingSymbol` (for display + storage), `netQty` (for quantity shown on button), `avgPrice` (for avg price shown on button).

**Note on `instrument_token`:** The positions DataFrame may or may not include the broker's internal instrument token. If not present, store `None` for now — it is informational only in the deployment file and not used for order placement (symbol string is used for orders).

**Note on `avgPrice` field name:** Must be verified on first live run. Possible variations: `avgPrice`, `avgCostPrice`, `buyAvg`, `costPrice`. The wizard should try known candidates and log a warning if none found.

---

### 2. Symbol Construction for ATO Strikes

The ATO symbol (e.g. `NIFTY25APR23950PE`) needs to be constructed from the sell leg's symbol. The pattern is:

```python
# Given pe_sell symbol: "NIFTY25APR24000PE"
# ATO symbol:           "NIFTY25APR23950PE"  (same prefix, different strike, same type)

# Parse sell symbol — regex from CONTEXT.md (Section 4):
import re
pattern = r'^([A-Z]+\d{2}[A-Z]{3})(\d+)(CE|PE)$'
# Group 1: "NIFTY25APR"  (underlying + expiry)
# Group 2: "24000"       (strike as string)
# Group 3: "PE"          (option type)

match = re.match(pattern, pe_sell_symbol)
prefix  = match.group(1)      # "NIFTY25APR"
opt_type = match.group(3)     # "PE"

pe_ato_symbol = f"{prefix}{pe_ato_strike}{opt_type}"
# Result: "NIFTY25APR23950PE"

ce_ato_symbol = f"{prefix}{ce_ato_strike}{opt_type}"
# For CE: prefix from ce_sell_symbol, type = "CE"
# Result: "NIFTY25APR24850CE"
```

This avoids any broker API call for ATO symbol construction. Pure string manipulation. No lookup needed.

---

### 3. Position Filtering — Implementation

```python
def is_nifty_option(symbol: str) -> bool:
    """Return True if symbol is a NIFTY options contract (CE or PE)."""
    return (
        symbol.upper().startswith("NIFTY") and
        (symbol.upper().endswith("CE") or symbol.upper().endswith("PE")) and
        not symbol.upper().startswith("NIFTYBEES") and   # exclude ETF
        not symbol.upper().startswith("NIFTYIT")         # exclude sector index
    )
```

Apply this filter to `tradingSymbol` column of positions DataFrame.

---

### 4. Expiry Extraction from Symbol

To store the `expiry` field in the deployment JSON:

```python
# Given symbol: "NIFTY25APR24000PE"
match = re.match(r'^NIFTY(\d{2}[A-Z]{3})', symbol)
expiry = match.group(1)   # "25APR"
```

---

### 5. Strike Extraction from Symbol

```python
match = re.match(r'^[A-Z]+\d{2}[A-Z]{3}(\d+)(CE|PE)$', symbol)
strike = int(match.group(1))   # 24000
```

---

### 6. ATO Module — Test Preservation Strategy

`modules/ato_protection.py` currently has **99/99 tests passing**. The deployment file read will be a new dependency. To avoid breaking tests:

- Add a new method: `_load_deployment_file()` — reads from `data/deployments/batman_*.json`
- Existing state keys (`ato.ce_protect_symbol`, `ato.pe_protect_symbol`, etc.) are **KEPT** in state as a fallback
- Priority: deployment file → state fallback → WAIT if neither exists
- In tests: `conftest.py` creates a mock deployment file or patches `_load_deployment_file()` — existing tests don't need changing
- New tests added for: file found + arm, file not found + wait, file mtime change + hot-reload

---

### 7. broker.py — Auth Mode (Pending)

Current `BatmanBroker.connect()` uses `pin_totp` mode. This needs to change to `access_token` mode:

```python
# Current (to be removed):
tsl = Tradehull(ClientCode=..., mode="pin_totp", pin=..., totp_secret=...)

# Target (when broker.py is updated — Priority 4):
tsl = Tradehull(ClientCode=..., mode="access_token", access_token=...)
```

**DRISHTI hot-updates this.** The KAVACH wizard does NOT depend on this change — `get_positions()` works regardless of auth mode. Only DRISHTI bot coding (Priority 3) depends on this change.

**Broker singleton rule (LOCKED):** `BatmanBroker` is a **single shared instance** created at startup and passed to all modules. DRISHTI updates the token on this shared instance (hot-reload). KAVACH reads positions from the same instance. No per-bot broker duplication.

---

### 8. Profit Trailing — Expiry-Agnostic Design (LOCKED 2026-04-04)

Current `modules/profit_trailing.py` reads `strategy.expiry_day` from `settings.json` and only runs on that weekday. This breaks for non-Tuesday deployments (monthly expiry, mid-week rolls, etc.).

**Decision:** `profit_trailing.py` will read expiry from the **deployment file**, not `settings.json`.

The deployment file already stores `expiry` per leg (e.g. `"25APR"`). From this, the expiry weekday can be derived:

```python
# From deployment file: positions.pe_sell.expiry = "25APR"
# → Parse the date → derive day of week → pass to profit_trailing
# OR: store expiry_weekday directly in deployment file for simplicity
```

**Simplest implementation:** Add `"expiry_weekday": 1` (0=Mon, 1=Tue, ...) to the deployment file schema, calculated at wizard confirmation time from the expiry date. `profit_trailing.py` reads this field instead of `settings.json`.

Deployment file schema addition:

```json
{
  ...
  "expiry_weekday": 1,
  "_expiry_weekday_comment": "0=Mon 1=Tue 2=Wed 3=Thu 4=Fri. Derived from expiry date at wizard confirm time."
}
```

---

### 9. Edge Case: Empty Position List at Step 1

If `get_positions()` returns empty (no open positions):

```
Bot sends:
  "⚠️ No open NIFTY positions found on your broker account.
   Please deploy Batman on Dhan first, then run /deploy again."
Wizard exits. No archive is done (no file to overwrite yet → skip Step 0 archive).
Log event: wizard_no_positions.
```

Add `wizard_no_positions` to the events catalogue in the audit log.
