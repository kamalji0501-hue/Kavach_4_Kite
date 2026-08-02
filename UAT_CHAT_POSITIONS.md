# UAT daily session — Cursor screenshot → agent → Register

OCR on Sensibull PNGs is **disabled** when you use the **cursor_chat** book.  
Agent does diagnose, fix, cleanup, restart, and verify — you only **tap Register** at the end.

---

## FAST PATH (default — use this every day)

**When:** bots already **RUNNING**, you only have a **new screenshot** / new legs.  
**Time:** ~1–2 min (agent). **No stop/start. No 180s wait. No daily test suite.**

KAVACH reloads `positions.json` **inside the running process** when you tap **Register**
(`refresh_fixture_positions` + `cursor_chat` skip OCR). Restart is **not** required for a book change.

### Copy-paste (attach Sensibull screenshot in same message)

```
@UAT_CHAT_POSITIONS.md @uat-sensibull-from-chat

FAST UAT POSITIONS — no bot restart.

1. Read screenshot → write uat/deployed_positions/positions.json (source=cursor_chat, leg order pe_sell/pe_buy/ce_buy/ce_sell)
2. Copy image → uat/deployed_positions/sensibull_chat_latest.png
3. Run: .venv\Scripts\python.exe scripts\quick_uat_positions_gate.py
4. Reply: OK + expiry + 4-leg table + "Tap Register in KAVACH"

Do NOT stop/start bots. Do NOT run daily test suite unless I say FULL UAT.
If KAVACH STOPPED → start KAVACH only (not full Phase 1 restart) unless I ask.
If Batman armed → cleanup runs in step 3; else Register handles it.
```

**Even shorter (voice):**

> FAST UAT positions from screenshot. No restart. quick_uat_positions_gate. Tap Register when OK.

### When you still need FULL daily prompt (restart + suite)

- First boot of the day and you want full log proof
- You changed **KAVACH/DRISHTI code**
- Bots crashed, duplicate instances, or JWT/LTP broken
- After **manual** `stop Kavach` / laptop reboot (shadow ledger may need cleanup — full prompt runs Phase C+D)

---

## What you do each day (operator)

| Step | You | Agent |
|------|-----|-------|
| 1 | New **Cursor Agent** chat → attach **Sensibull screenshot** → paste **Daily UAT prompt** (below) | Reads image, writes `positions.json`, fixes issues, cleans up, restarts bots, verifies |
| 2 | Wait for agent finish report | Must end with **`OK: ...positions.json`** + **`Tap Register in KAVACH now`** |
| 3 | Open **KAVACH Telegram** → tap **Register** | Log should say **`cursor_chat` (skip OCR)** — not OCR |
| 4 | Complete wizard (PE/CE, buffers, confirm) | — |
| 5 | Optional quick check only | `Execution\Apply UAT Chat Positions.bat` (validates JSON; agent already ran this) |

**After KAVACH restart:** you must **re-register**. Agent handles cleanup + restart in the daily prompt — do not skip step 1.

**Quick JSON-only day (no restart):** use **Shortcut only** at bottom — then Register yourself if bots already healthy.

---

## Daily UAT prompt (copy-paste — attach screenshot in same message)

This is your **main** prompt. Use it every trading day and whenever you restart KAVACH.

```
@UAT_CHAT_POSITIONS.md @UAT_E2E_AGENT.md @AGENTS.md

You are the Batman UAT daily session agent. Execute everything yourself.
Do NOT ask me to run terminal commands, debug logs, or test Telegram buttons.

CONTEXT
- Mode: uat only (ShadowBroker virtual orders; real Dhan LTP via marketfeed API).
- Book: uat/deployed_positions/positions.json source=cursor_chat (from my screenshot).
- After KAVACH restart: shadow ATO fills are lost unless ledger restored — cleanup + fresh Register required.
- Prod boundary: never enable ShadowBroker outside uat; shared ATO logic, different broker backend.

══════════════════════════════════════════════════════════════
PHASE A — SCREENSHOT → positions.json
══════════════════════════════════════════════════════════════
1. Read attached Sensibull New Strategy screenshot:
   - Weekly expiry (any date — e.g. 09 Jun 2026)
   - 4 legs: B/S, strike, CE/PE, lots, avg price
   - Leg order in JSON: pe_sell, pe_buy, ce_buy, ce_sell (PE strikes ascending, CE ascending)
2. Write uat/deployed_positions/positions.json:
   - source: "cursor_chat"
   - expiry_date ISO + expiry_label human
   - Use scripts/write_uat_chat_positions.py or core/uat_chat_positions.py
3. Copy screenshot → uat/deployed_positions/sensibull_chat_latest.png (if not already there)
4. Validate:
   .venv\Scripts\python.exe backtest_engine\tools\validate_fixture.py uat\deployed_positions\positions.json
5. Reply: OK: <full path>\positions.json | expiry=... | 4 legs summary table

══════════════════════════════════════════════════════════════
PHASE B — DIAGNOSE & FIX (before restart)
══════════════════════════════════════════════════════════════
1. Confirm UAT mode:
   - config/batman_mode.json mode=uat (run Mode\Set-UAT.bat if needed)
2. Diagnose all Phase 1 bots:
   .venv\Scripts\python.exe scripts\diagnose_robot.py drishti
   .venv\Scripts\python.exe scripts\diagnose_robot.py kavach
   .venv\Scripts\python.exe scripts\diagnose_robot.py jagran
3. Read today IST logs:
   logs_uat/runtime/YYYY-MM/YYYY-MM-DD/kavach/logs/all.log
   logs_uat/runtime/.../kavach/errors/all_errors.log
   Same for drishti, jagran
4. Classify errors:
   - Process dead → restart in Phase D
   - JWT expired → DRISHTI token refresh → data/access_token.json (read from disk; never ask me to paste)
   - Stale NIFTY cache → fix DRISHTI first, then KAVACH
   - Positions missing ATO leg / wrong prices → fix ShadowBroker/ledger/enrich; minimal code diff + pytest
   - HTTP 429 marketfeed → reduce duplicate polls; batch get_nifty_option_ltps
5. If market hours (09:15–15:30 IST), probe live Dhan APIs:
   .venv\Scripts\python.exe scripts\probe_dhan_option_ltp.py
   Expect: NIFTY REST OK + marketfeed NSE_FNO for legs (Tradehull symbol LTP may fail — OK, we use securityId path)
6. Fix loop: implement → pytest → re-diagnose (max 4 cycles)

══════════════════════════════════════════════════════════════
PHASE C — CLEANUP FOR FRESH REGISTER (mandatory)
══════════════════════════════════════════════════════════════
Run cleanup when ANY of these is true:
- KAVACH was or will be restarted
- deployment.confirmed=True in data/uat/batman_state.json
- Old batman_*.json in data/uat/deployments/
- data/uat/shadow_order_ledger.json has virtual ATO orders from prior session
- New screenshot / new book while previously armed

Cleanup actions (agent executes — I do NOT tap Batman Complete):
1. Archive active deployments (prepare_uat_register_fresh / _archive_active_deployments)
2. Clear shadow virtual book:
   - data/uat/shadow_order_ledger.json via clear_ledger / clear_virtual_book
3. Reset data/uat/batman_state.json:
   - deployment.confirmed=False, deployment.batman_complete=False
   - ato.ce_triggered/pe_triggered and order ids cleared
   - positions.ce_sell/buy/pe_sell/buy cleared
   - algo.paused=False
4. KEEP the new cursor_chat positions.json from Phase A (do NOT delete it)

══════════════════════════════════════════════════════════════
PHASE D — RESTART ROBOTS (order matters)
══════════════════════════════════════════════════════════════
1. Stop all:
   Execution\Stop Bots\Phase 1 Stop All Robots.bat
   OR .venv\Scripts\python.exe scripts\stop_all_phase1.py
2. Verify STOPPED:
   .venv\Scripts\python.exe scripts\bot_status.py all
   Show Bot Status.bat must show STOPPED before start
3. Start all:
   Execution\Start Bots\Phase 1 Start All Robots.bat
   - DRISHTI first → wait for fresh data/nifty_ltp_cache.json (source dhan_rest)
   - KAVACH second → must log: cursor_chat positions.json ready + ShadowBroker loaded core legs
   - JAGRAN third
4. UAT wait 180s; confirm each bot RUNNING, single instance (no ORPHAN / duplicate KAVACH)
5. If KAVACH only needed:
   Execution\Stop Bots\stop Kavach.bat → Execution\Start Bots\start Kavach.bat
   Still run Phase C cleanup before restart if re-registering

══════════════════════════════════════════════════════════════
PHASE E — VERIFY GATE (agent-owned)
══════════════════════════════════════════════════════════════
.venv\Scripts\python.exe scripts\audit_bot_tokens.py
.venv\Scripts\python.exe scripts\phase1_bot_check.py
.venv\Scripts\python.exe scripts\run_uat_daily_test_suite.py
  (or scripts\run_uat_e2e_verification.py if faster)

Confirm:
- 4 core legs in ShadowBroker get_positions with avg prices (fixture + live enrich)
- ATO protect leg (e.g. 23450 CE) appears only when breach active + virtual BUY in ledger
- Register path will use cursor_chat (ingest log: skip OCR)
- No new ERROR in kavach logs (stale cache warning OK for ~30s after DRISHTI start)

Re-run verify after fixes (max 4 cycles).

══════════════════════════════════════════════════════════════
PHASE F — HANDOFF (what you tell me)
══════════════════════════════════════════════════════════════
Report in this format:

OK: uat\deployed_positions\positions.json
Expiry: ...
Legs: pe_sell ... | pe_buy ... | ce_buy ... | ce_sell ...
Cleanup: deployments archived=... | state reset=... | shadow ledger cleared=...
Bots: DRISHTI=RUNNING | KAVACH=RUNNING | JAGRAN=RUNNING
JWT: ok / refreshed at ...
Tests: daily suite PASS n/m (or e2e PASS)
Logs: no errors in <paths>

>>> Tap Register in KAVACH Telegram now.
    Expect log: UAT register: using cursor_chat positions.json (skip OCR)
    Then complete PE/CE wizard and confirm deploy.

Do not ask me to test Positions or Register — you verified handlers and logs.
```

---

## Shortcut only (positions.json — no restart)

Same as **FAST PATH** above. Script: `scripts/quick_uat_positions_gate.py` or `Execution\Quick UAT Positions.bat`.

```
UAT POSITIONS. Read the Sensibull screenshot (note expiry + 4 legs) and write positions.json for UAT Register.
@uat-sensibull-from-chat
```

Attach screenshot → agent runs **quick_uat_positions_gate** → wait for **`OK: ...positions.json`** → tap **Register** in KAVACH.

If KAVACH was restarted since last Register, use the **Daily UAT prompt** above instead.

---

## After Register

| Check | Expected |
|-------|----------|
| Register ingest log | `cursor_chat` · skip OCR |
| **Positions** menu | 4 core legs, expiry like **09 Jun 2026**, prices filled (not ₹—) |
| CE breach + ATO | 5th leg (protect strike) with **ATO** tag; live LTP from Dhan marketfeed |
| **Core Legs** menu | Registered deployment legs from wizard |

---

## Re-register same day

1. New screenshot + **Daily UAT prompt** (agent overwrites `positions.json`, cleanup, restart if needed)
2. **Register** again in KAVACH

If armed with old book without cleanup → Register may block or show wrong legs. Agent Phase C prevents this.

---

## Related files

| File | Role |
|------|------|
| `skills/uat-sensibull-from-chat/SKILL.md` | Agent skill for screenshot parsing |
| `UAT_E2E_AGENT.md` | E2E test loop after code changes |
| `Execution\Quick UAT Positions.bat` | Fast gate — validate + cleanup, **no restart** |
| `Execution\Apply UAT Chat Positions.bat` | Validate JSON only |
| `data/uat/shadow_order_ledger.json` | Virtual ATO orders (cleared on cleanup) |
