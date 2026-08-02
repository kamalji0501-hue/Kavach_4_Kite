# KAVACH Bot — Context & Handoff (Phase 1 Gates 2–4 partial)

**Status:** 🟡 **Planning locked** — operator rules in **`docs/KAVACH_ATO_OPERATOR_RULES.md`** (2026-06-20); implementation pending operator **go**  
**Last updated:** 2026-06-20  
**Owner:** Rahul  
**Bot:** `@kavach_ATO_Bot`

> **Authoritative operator rules (ATO, register, Complete, manual legs):**  
> **`docs/KAVACH_ATO_OPERATOR_RULES.md`** — supersedes conflicting notes in this file §12 “archive → re-register” and `kavach_design.md` Step 0.

---

## 1. What KAVACH does (locked)

| Responsibility | Status |
|----------------|--------|
| Register 4-leg iron condor (`/register` wizard) | ✅ Live — Rahul completed 2026-05-29 |
| Read broker positions for leg pick | ✅ Dhan REST + Tradehull fallback |
| Button menu (no slash-command list) | ✅ Approved |
| Deployment file + state sync | ✅ `batman_2026-05-29_19-09.json` armed |
| ATO protect symbol calc | ✅ Fixed for Dhan hyphenated symbols |
| `/positions`, `/legs`, `/status`, `/funds`, `/ato_status` | ✅ Via menu buttons — MarkdownV2 fix 2026-05-30 |
| Pause / Resume / Start Algo Now / Batman Complete | ✅ Coded |
| Daily 09:25 ATO monitoring gate | ✅ `core/ato_monitoring_schedule.py` + Status/ATO Status line |
| ATO monitoring module (live/simulated) | 🔜 Gate 5 — not running in standalone |
| `/exit` emergency close | ❌ Out of Phase 1 scope |

**Does NOT own:** Dhan JWT (DRISHTI), NIFTY LTP feed (DRISHTI / Gate 1.4).

---

## 2. Operator UI (final — approved)

### Alive menu (home screen only)

After `/start`, `/ping`, or any unknown message:

```
🟢 KAVACH alive
29-May-2026 HH:MM:SS IST
Deployment: Armed (batman_2026-05-29_19-09.json)

[Register]      [Positions]
[ATO Status]    [Legs]
[Status]        [Funds]
[Pause]         [Resume]
[Start Algo Now]
[Batman Complete]
```

**Removed:** Long slash-command help list (`_HELP` deleted).

### Register wizard

- Entry: **Register** button or `/register` (must go through `ConversationHandler` entry points)
- Step order (locked): PE BUY → PE SELL → CE BUY → CE SELL
- Step labels include direction hints: LONG PE, SHORT PE, LONG CE, SHORT CE
- On confirm: success message + alive menu with **Armed** status

---

## 3. Current deployment (armed — 2026-05-29 19:09 IST)

**File:** `data/deployments/batman_2026-05-29_19-09.json`  
**State:** `data/batman_state.json` — `deployment.confirmed: true`  
**Wizard type:** Legacy full 4-leg register (pre–§12 side-scoped). §12/§13 code is live for next re-register.

| Leg | Symbol | Qty | Strike |
|-----|--------|-----|--------|
| PE BUY | NIFTY-Jun2026-23750-PE | 910 LONG | 23750 |
| PE SELL | NIFTY-Jun2026-23700-PE | 1820 SHORT | 23700 |
| CE BUY | NIFTY-Jun2026-25300-CE | 3770 LONG | 25300 |
| CE SELL | NIFTY-Jun2026-25000-CE | 3770 SHORT | 25000 |

**ATO settings (from wizard):**

| Setting | Value |
|---------|-------|
| Manage sides | both |
| Poll interval | 1 sec |
| CE entry buffer | 10 pts |
| PE entry buffer | 10 pts |
| CE retrace | 20 pts |
| PE retrace | 25 pts |
| ATO step | 50 |
| Break-even | skipped |

**ATO protect symbols:**

| Side | Symbol | Strike |
|------|--------|--------|
| PE | NIFTY-Jun2026-23650-PE | 23650 |
| CE | NIFTY-Jun2026-25050-CE | 25050 |

**Calendar:** deploy 2026-05-29 · expiry 2026-06-02 · 3 working days

---

## 4. How to run (Windows)

| Action | Command / file |
|--------|----------------|
| **Start KAVACH** | `Execution\Start Bots\start Kavach.bat` |
| **Stop KAVACH** | `Execution\Stop Bots\stop Kavach.bat` |
| **Start DRISHTI** | `Execution\Start Bots\start Drishti.bat` (JWT required first) |
| **Standalone KAVACH** | `python run_kavach.py` |
| **Positions smoke** | `python scripts\fetch_positions.py` |
| **All bots check** | `python scripts\phase1_bot_check.py` |
| **Logs** | `logs/bots/kavach/logs/startup.log` |

**After laptop restart:**

1. Start **DRISHTI** first → paste/confirm Dhan JWT if expired
2. Start **KAVACH** → broker connects from `data/access_token.json`
3. Send `/start` on `@kavach_ATO_Bot` → should show **Armed** with deployment filename

**Important:** One KAVACH instance only (`data/kavach.lock`).

---

## 5. Key files (this session)

| File | Role |
|------|------|
| `bat_telegram/bots/kavach/bot.py` | Button menu, wizard, read-only commands, `_md2()` / `_md2_code()` |
| `bat_telegram/bots/kavach/KAVACH_CONTEXT.md` | **This handoff doc** |
| `core/positions.py` | **NEW** — REST fetch, filter, ATO symbol builder, expiry parse |
| `core/broker.py` | Tradehull token cache sync + REST positions fallback |
| `run_kavach.py` | **NEW** — standalone runner (broker + state + event bus) |
| `scripts/stop_kavach.py` | **NEW** — process stop |
| `scripts/fetch_positions.py` | **NEW** — Gate 3 positions smoke |
| `Execution/Start Bots/start Kavach.bat` | **NEW** |
| `Execution/Stop Bots/stop Kavach.bat` | **NEW** |
| `tests/test_positions.py` | **NEW** — 11 unit tests (all pass) |
| `telegram/bots/kavach/token.env` | ✅ Configured — `@kavach_ATO_Bot` |
| `telegram/bots/jagran/token.env` | ✅ Configured — `@jagran_bot` |

---

## 6. Positions architecture

```
User taps Positions / Register
    → broker.get_positions()
    → try Tradehull (with fresh JWT cache sync)
    → if fail → Dhan REST /v2/positions
    → filter_nifty_positions() in core/positions.py
    → show legs or wizard keyboard
```

**Dhan symbol format:** `NIFTY-Jun2026-23700-PE` (hyphenated) — not compact `NIFTY25APR…`.

**ATO symbol builder:** `build_ato_protect_symbol()` preserves hyphenated format.

---

## 7. Smoke test evidence (2026-05-29)

| Test | Result |
|------|--------|
| All 3 bots `phase1_bot_check.py` | ✅ PASS |
| Live positions fetch (4 NIFTY legs) | ✅ PASS |
| Register wizard end-to-end | ✅ PASS — Rahul confirmed |
| Deployment file written | ✅ `batman_2026-05-29_11-51.json` |
| State synced | ✅ `deployment.confirmed: true` |
| Unit tests `test_positions.py` | ✅ 11/11 pass |

### Issues resolved this session

| Issue | Fix |
|-------|-----|
| KAVACH/JAGRAN tokens missing | `token.env` filled for both bots |
| Register from menu — leg clicks ignored | Added `wizard_entry_menu` as `ConversationHandler` entry point |
| Leg click — MarkdownV2 crash on `-` in symbols | `_md2()` escape via `escape_markdown` |
| Wrong ATO protect symbols | `build_ato_protect_symbol()` + patched deployment/state |
| Tradehull stale JWT cache | `_sync_tradehull_token_cache()` in broker connect |
| Tradehull positions fail | REST fallback in `broker.get_positions()` |
| Wizard state unpack bug | `range(18)` for 18 conversation states |
| Garbage expiry field | `parse_position_expiry()` from `drvExpiryDate` |
| Positions menu — `BadRequest: character '.' reserved` | `_md2()` on avg_price; `_md2_code()` for inline code; same pattern in Legs/Funds/ATO Status |

---

## 7b. MarkdownV2 helpers (2026-05-30)

```python
def _md2(text: str) -> str:
    """Escape dynamic text outside inline code (prices, labels)."""
    return escape_markdown(str(text), version=2)

def _md2_code(text: str) -> str:
    """Escape dynamic text inside inline code spans (symbols, balances)."""
    return escape_markdown(str(text), version=2, entity_type="code")
```

**Fixed handlers:** `cmd_positions`, `cmd_legs`, `cmd_funds`, `cmd_ato_status`

**Operator retest after restart:** Tap Positions → should show lines like  
`` `NIFTY-Jun2026-23700-PE` — SHORT 1820 @ ₹27.00 `` (no Telegram parse error).

---

## 8. Credentials (gitignored — do not commit)

| File | Status |
|------|--------|
| `telegram/bots/kavach/token.env` | ✅ Configured |
| `telegram/bots/jagran/token.env` | ✅ Configured |
| `telegram/bots/drishti/token.env` | ✅ Configured |
| `config/.env` | ✅ `DHAN_CLIENT_CODE` |
| `data/access_token.json` | ✅ Dhan JWT (refresh daily via DRISHTI) |

**Chat IDs:** DRISHTI + KAVACH → private `260692573`. JAGRAN → group **Batman Alerts** `-5174160875`.

---

## 9. Gate progress (where KAVACH stands)

| Gate | Status |
|------|--------|
| Gate 2 — Telegram bots | 🟡 ~90% — all 3 PASS; JAGRAN standalone verified |
| Gate 3 — Dhan positions | 🟡 ~85% — live fetch PASS; Positions menu fix applied (retest pending) |
| Gate 4 — KAVACH configured | 🟡 ~75% — wizard + armed deployment; ATO module not wired |
| Gate 5 — ATO test | ⬜ Pending |
| Gate 1.4 — persistent 1s NIFTY feed | ⬜ Needed for ATO in production |

---

## 10. Next session — after tool/laptop restart

1. Start DRISHTI → confirm JWT valid (Update Token if needed)
2. Start KAVACH → verify **Armed** on `/start` (`batman_2026-05-29_19-09.json`)
3. Start JAGRAN → Test Alert in Batman Alerts group
4. Tap **Positions** / **Legs** / **Funds** / **ATO Status** — confirm no MarkdownV2 errors
5. Optional: `python scripts\phase1_bot_check.py` — all 3 PASS
6. **Next work:** Gate 5 ATO simulated test OR re-register with §12 side-scoped wizard
7. Later: persistent NIFTY websocket feed (Gate 1.4) for 1s ATO poll

---

## 11. Related documentation

| File | Role |
|------|------|
| `bat_telegram/bots/drishti/DRISHTI_CONTEXT.md` | DRISHTI complete reference |
| `CONTEXT.md` §15 | Project master handoff |
| `PHASE1_IMPLEMENTATION_PLAN.md` | 7-gate rollout |
| `PHASE1_REQUIREMENTS.md` | Locked operator behavior |
| `PHASE1_DHAN_INTEGRATION.md` | Dhan API notes |
| `PHASE1_OPEN_QUESTIONS.md` | Remaining open items |

---

*KAVACH Phase 1: §12 side-scoped registration + §13 custom buffers **implemented** (2026-05-29). Simulator wizard parity still legacy.*

---

## 12. Side-scoped registration + partial lots (IMPLEMENTED)

**Status:** ✅ Implemented in `register_wizard.py` + deployment schema v1.1  
**Purpose:** Controlled algo ownership — PE/CE independent, partial lots, skip side, no empty registration.

### Wizard flow (full path always — no shortcuts)

```
Register → fetch broker positions

PE side intent     [ Enable PE ]  [ Skip PE ]
  If Enable PE:
    PE BUY (LONG PE) → PE SELL (SHORT PE)
    → validate exact 1:2 ratio on SELL pick (fail = message + re-pick SELL, JAGRAN incident)
    → PE lot buttons: 1 … max_pe + [ Use all (max_pe) ]

CE side intent     [ Enable CE ]  [ Skip CE ]
  If both skipped → cancel: "Select at least one side"

  If Enable CE:
    CE BUY → CE SELL
    → validate exact 1:2 on CE SELL pick (same fail behavior)
    → CE lot buttons: 1 … max_ce + [ Use all (max_ce) ]

Existing ATO steps (buffers, retrace, poll) — unchanged count/behavior

ATO monitoring mode (existing step):
  • Both sides registered: [ PE only ] [ CE only ] [ Both ] — user may register both but monitor PE only
  • PE only registered: [ PE only ] active + note "CE disabled (not registered)"
  • CE only registered: [ CE only ] active + note "PE disabled (not registered)"

Confirm summary → show only registered sides + managed lots/qty
```

### Lot / quantity rules

| Rule | Value |
|------|--------|
| Lot size | 65 qty = 1 NIFTY lot (broker/config) |
| UI | **Buttons only** — no free text; show **all** lot values 1…max + **Use all** on same screen |
| Max lots per side | `min(buy_lots, sell_lots ÷ 2)` |
| Managed qty | BUY = `lots × 65`; SELL = `lots × 2 × 65` (standard 1:2 per side) |
| Expiry | **Different expiries allowed** across legs — user responsibility |
| Ratio | **Exact 1:2 required** per side at SELL pick — block registration + JAGRAN if wrong |

### Skip / add side later

- PE-only, CE-only, or both — all valid.
- To change sides or settings later: **`Batman Complete` → verified cleanup → auto `/register` wizard** (no register-over-register while armed). See **`docs/KAVACH_ATO_OPERATOR_RULES.md` §3**.

### Runtime broker mismatch

- If broker Batman qty &lt; registered managed qty (manual partial close on Dhan): **pause that side**, **warn**, **JAGRAN** — recovery = **Batman Complete** → re-register (Q41). See **`docs/KAVACH_ATO_OPERATOR_RULES.md` §16.1**.

### Deployment schema (planned v1.1)

```json
"registration_scope": {
  "pe_enabled": true,
  "ce_enabled": false,
  "pe_managed_lots": 14,
  "ce_managed_lots": null,
  "lot_size": 65
},
"positions": {
  "pe_buy":  { "qty": 910,  "broker_qty": 910,  ... },
  "pe_sell": { "qty": 1820, "broker_qty": 1820, ... },
  "ce_buy":  null,
  "ce_sell": null
}
```

- `qty` = algo-managed; `broker_qty` = snapshot at register.
- ATO `_ato_qty()` uses managed `qty` only.

### Implementation order (when approved)

1. `core/position_scope.py` + unit tests  
2. KAVACH wizard states + keyboards  
3. `_write_deployment_file` / `_sync_state_from_deployment_file`  
4. ATO reconciliation + JAGRAN on mismatch  
5. Simulator parity  

### Out of scope

- SARANSH / PnL lot display  
- Partial add-side without re-register  
- Free-text lot entry  

### UX decisions (G1–G3 final)

| ID | Decision |
|----|----------|
| G1 | Show active monitoring button(s) + **disabled options with notes** (what is disabled and why) |
| G2 | Ratio fail → **re-pick SELL** without restarting wizard |
| G3 | **All lot buttons visible** (multi-row grid); layout not critical |

---

## 13. Custom ATO buffer entry/exit (IMPLEMENTED)

**Status:** ✅ Predefined + custom decimal buffers in wizard; typed deployment fields; Decimal trigger math in `ato_protection.py`

### Terminology map (prompt → codebase)

| Prompt term | KAVACH / ATO today |
|-------------|-------------------|
| Entry Buffer Points | `ce_entry_buffer_points`, `pe_entry_buffer_points` (wizard `_buffer_keyboard`) |
| Exit Buffer Points | `ce_retrace_points`, `pe_retrace_points` (wizard `_retrace_keyboard`) |
| Predefined options | Entry: `0, 5, 10, 15, 20` · Exit/retrace: `0–50` step 5 |
| Trigger calc | `modules/ato_protection.py` → `_side_settings()` |

### Objective

Hybrid model per buffer (entry + exit), **per side** (CE and PE unchanged):

```
Select buffer mode:  [ Predefined ]  [ Custom ]

Predefined → existing button grid (unchanged behavior)
Custom     → Telegram text input → validate → store decimal value
```

Support **int and decimal** buffers (e.g. `0.5`, `2.25`, `15.25`) using `decimal.Decimal` in trigger math.

### Validation (config-driven)

```json
"ato": {
  "buffer_min": 0.1,
  "buffer_max": 100.0,
  "predefined_entry_buffers": [0, 1, 2, 3, 4, 5, 10, 15, 20],
  "predefined_exit_buffers": [0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
}
```

Reject: non-numeric, ≤ 0, empty, out of range, special chars.  
Reprompt: `❌ Invalid buffer points. Enter a positive number (e.g. 1.5).`

### Enhanced deployment / state model (v1.2 — backward compatible)

Legacy (still valid):

```json
"ce_entry_buffer_points": 5,
"ce_retrace_points": 10
```

Enhanced (additive):

```json
"ce_entry_buffer": { "type": "CUSTOM", "value": "2.5" },
"ce_exit_buffer":   { "type": "PREDEFINED", "value": "5" }
```

Loaders accept **either** legacy int fields or new typed objects. Old deployments unchanged.

### Wizard state additions

```
WIZARD_CE_ENTRY_MODE → WIZARD_CE_ENTRY_CUSTOM (MessageHandler)
WIZARD_PE_ENTRY_MODE → WIZARD_PE_ENTRY_CUSTOM
WIZARD_CE_EXIT_MODE  → WIZARD_CE_EXIT_CUSTOM   (retrace)
WIZARD_PE_EXIT_MODE  → WIZARD_PE_EXIT_CUSTOM
```

### Module layout (project convention — not `/coverage_bot`)

```
core/buffer_config/
  __init__.py
  parser.py      # parse user text → Decimal
  validator.py   # min/max, positive rules
  schema.py      # typed buffer dict ↔ legacy int
tests/test_buffer_config.py
```

### ATO integration changes

- `_side_settings()` → return `Decimal` buffers; `trigger_level` / `exit_level` as `Decimal`
- Compare NIFTY spot (`float`) using `Decimal(str(spot))` or quantize policy (document in code)
- Telemetry CSV: store buffer values as string decimals
- **No change** to order qty logic — buffers affect **index trigger levels** only

### UX rules

- Summary shows: `CE entry: 2.5 pts (custom)` vs `PE entry: 5 pts (predefined)`
- Predefined path = **exact** current behavior
- Custom path = text reply step (Telegram `MessageHandler`)

### Testing

| Suite | Cases |
|-------|--------|
| Predefined | Existing wizard + ATO trigger math unchanged |
| Custom | 0.5, 1.25, 2.75, 15.25 → correct trigger/exit levels |
| Invalid | abc, -5, 0, empty, 999 |
| Backward compat | Old JSON without `type` fields loads as PREDEFINED ints |

### Out of scope (future)

- ATR/volatility auto buffers  
- Instrument-specific defaults beyond config JSON  
- SARANSH  

### Implementation order (relative to §12)

Recommended: **§12 side-scoped registration first**, then **§13 custom buffers** (both touch wizard states).  
Or: §13 first if Rahul prioritizes buffer tuning over partial lots.

### Open items (confirm before coding §13)

| ID | Question | Default |
|----|----------|---------|
| B1 | Predefined entry list: keep `0,5,10,15,20` or switch to prompt’s `1,2,3,4,5,10`? | **Merge** both sets via config |
| B2 | Custom input allowed for **0** buffer (instant trigger)? | **No** — min 0.1 per validation |
| B3 | Decimal precision display: max 2 decimal places? | **Yes** — quantize `0.01` |
