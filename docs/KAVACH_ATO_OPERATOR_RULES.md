# KAVACH / ATO — Operator Rules & Scenario Bible

**Status:** IMPLEMENTATION IN PROGRESS — operator discovery locked (Q1–Q46); coding started 2026-06-20  
**Audience:** Operator (Rahul) + implementation agent  
**Scope:** Business logic, trading decisions, operational scenarios — **not** code structure  
**Supersedes:** Conflicting passages in `kavach_design.md` Step 0, `KAVACH_CONTEXT.md` §12 “archive → re-register”, `PHASE1_REQUIREMENTS.md` “max cycles unlimited”

**Related (engineering):**
- `bat_telegram/bots/kavach/register_wizard.py` — wizard UX
- `modules/ato_protection.py` — breach / retrace loop
- `core/position_scope.py` — lots, strikes, registration scope
- `core/batman_cleanup.py` — post-Complete verification
- `telegram/bots/kavach/params.json` — tunables (no hardcoded limits in code)

---

## 1. Philosophy

| Principle | Rule |
|-----------|------|
| **Operator is final** | Strike, ATO lots, buffers — system **warns**, rarely blocks (except invalid strike, cleanup fail, register gate) |
| **UAT = prod behaviour** | Same rules in shadow broker and live VPS; UAT mimics prod for scenario testing |
| **Economy / chop testing** | Far OTM protect (e.g. sell 24,500 CE → protect 26,000 CE) + low ATO lots to exercise cycles cheaply |
| **Trigger ≠ protect** | **When** ATO fires = **sell strike** (+ entry buffer). **What** is bought/sold = **protect strike** you chose |
| **Local book is truth** | Broker/shadow positions validate fills; odd qty never happens — always **multiples of 65** (1 NIFTY lot) |
| **Only registered protect leg** | KAVACH never touches other positions you hold for your own reasons |

---

## 2. Lifecycle overview

```
┌─────────────────────────────────────────────────────────────────┐
│  FIRST TIME / NEW BATMAN WEEK                                   │
│  Dhan: deploy iron condor manually                              │
│  KAVACH: /register (wizard) → Confirm → ATO armed immediately   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  NEW SETTINGS MID-WEEK (REVISED — Q24)                          │
│  /register while armed → BLOCKED                                │
│  → Batman Complete → cleanup (retry ≤3) → verify → auto wizard  │
│  → new Confirm → new deployment takes precedence                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  END OF BATMAN CYCLE                                            │
│  Batman Complete → archive + state reset + verify               │
│  Dhan positions NOT auto-closed                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Register gate & Batman Complete (Q24, Q36–Q40)

### 3.1 When `/register` is blocked

| Condition | Action |
|-----------|--------|
| Active deployment file exists (armed **or** paused) | **Block** — message: mark **Batman Complete** first |
| Cleanup verification failed after 3 retries | **Block** `/register` — JAGRAN + operator error |
| No active deployment | Normal wizard (fetch positions → questions) |

**Removed behaviour:** “Yes — start wizard anyway” while armed (old prod pre-confirm). **UAT no longer skips** this gate.

### 3.2 Batman Complete flow

1. Operator confirms Complete.
2. **Warn + list** any open **ATO protect legs** still on Dhan (does not block Complete).
3. Archive deployment, reset state, run `verify_batman_cleanup`.
4. On verify fail → **retry cleanup up to 3×** (config: `cleanup_retry_max`).
5. Still fail → error: *cleanup unsuccessful after 3 retries*; `/register` blocked; JAGRAN.
6. On verify pass → confirmation message → **auto-start regular register wizard** (no extra buttons).

### 3.3 Orphan legs after Complete + new register (Q40)

- Old protect leg (e.g. 26,000 CE) may remain on Dhan — **not auto-closed**.
- New register (e.g. 27,000 CE) manages **only** the new protect strike.
- **Warn at confirm** if orphan CE/PE longs detected outside new ATO scope.

---

## 4. Register wizard (current + planned)

### 4.1 Opening

- Announce position source: **“Positions from UAT shadow book”** or **“Positions from Dhan”**.
- Intro: up to **19 questions** when both sides enabled (PE block → CE block → shared → Confirm); count recalculates if side skipped.

### 4.2 Symmetric flow (both sides)

```
PE:  intent → BUY → SELL → managed lots → ATO lots → protect strike → entry buffer → exit buffer
CE:  (same)
Shared: poll interval → monitoring mode (PE / CE / both) → Confirm
```

### 4.3 ATO lots (operator choice)

| Input | Meaning |
|-------|---------|
| Integer ≥ 0 | Lots on breach (× 65 qty) |
| `0` | **Monitor only** — breach Telegram alert, **no order** (Q29, Q35: alert even before 08:00 quiet window) |
| > managed lots | **Warn** on confirm, allow |
| < managed lots | **Warn** partial ATO on confirm; **no extra alert at breach** (Q4) |

### 4.4 Protect strike

| Mode | Behaviour |
|------|-----------|
| **Auto** | CE: sell + 50 · PE: sell − 50 (`ato_step` in params) |
| **CE presets** | **Auto** (sell+50) · **+500** · **+1000** · Custom — **no minus** on CE (Q44) |
| **PE presets** | **Auto** (sell−50) · **−100** · **−500** · Custom — **no plus** on PE; protect is always **below** sell (Q44) |
| **Custom text** | Must be **strike % 50 == 0**; must **exist** for sell leg expiry — else **block Confirm** (Q6) |
| **Any custom** | **Warn** on confirm — economy / reduced hedge (Q19) |

### 4.5 Qty adoption at Confirm (register time)

| Broker vs register | Action |
|--------------------|--------|
| Protect leg **already open**, qty **lower** than ATO lots | Adopt **broker lots**; arm for that qty; warn (Q21) |
| Protect leg open, qty **higher** than ATO lots | Adopt **registered lots** for algo; warn excess outside scope (Q22) |
| Strike matches, qty matches | Adopt → **holding** state; exit-only until flat |

### 4.6 Confirm warnings (summary)

- Custom protect strike (any)
- ATO lots ≠ suggested / managed size
- Partial ATO / economy profile → SARANSH tag **Custom ATO / economy profile** (Q25)
- Orphan legs from prior cycle
- CE protect ≤ sell or PE protect ≥ sell (direction) — warn only

---

## 5. ATO trigger & exit logic

### 5.1 Entry (breach)

| Event | Action |
|-------|--------|
| NIFTY crosses sell + entry buffer (CE up / PE down) | **BUY** protect leg for **ATO lots × 65** |
| Already breached at Confirm / startup | **Buy immediately** (startup scan) (Q7) |
| ATO lots = 0 | Alert only — no order |
| NSE **holiday** | No monitoring (Q11) |
| **Expiry day** | Same rules until **15:15 IST** stop (Q10, Q71 **A**) — monitoring stops; open legs stay on Dhan |

### 5.2 Exit (retrace)

| Event | Action |
|-------|--------|
| NIFTY retraces per **exit buffer** vs **sell strike** | **SELL** full registered ATO qty held |
| **Pause active** | **No exit** while paused (Q20); on Resume use **current** spot |
| After manual full exit → pause → Resume, breach still on | **BUY immediately** if protect leg **absent** at broker — book-first validation (Q32C, Q56) |

### 5.3 Choppy session — soft cap (Q5, Q9, Q15)

| Setting | Default (config) |
|---------|------------------|
| First warn | After **3** complete cycles per side per day |
| Repeat warn | Every **2** cycles: 5, 7, 9… |
| Auto-stop | **Never** — operator pauses manually if needed |

*Cycle = one BUY + one SELL on that side.*

**Monitor-only (0 ATO lots):** breach alerts **do count** toward soft-cap chop warnings (Q43) — no orders, but chop exposure is tracked.

**Code gap:** `ato_protection.py` today uses **hard** `max_cycles_per_session` stop — must change to **soft warn only**.

---

## 6. Order placement & validation (Q8, Q12, Q13, Q33)

### 6.1 Algorithm (BUY and SELL)

```
1. Read local book (Dhan or UAT shadow)
2. If expected leg + qty (in lots × 65) already present → success, no retry
3. If missing or lot mismatch → place/retry order
4. After each attempt → re-read book
5. Max retries: 3 (config: order_retry_max)
6. Still wrong → pause THAT side + JAGRAN + operator message:
   "Check Dhan order portal — [BUY/SELL] [symbol] failed: [broker error]"
```

### 6.2 Partial lot fill

- Only **whole lots** (65, 130, 195…) — never 40 qty.
- Example: need 6 lots, book shows 3 lots → retry for **remaining 3 lots**.

### 6.3 Position book unreadable (Q33, Q62)

- On each ATO poll, read local book with **up to 3 retries** (same spirit as `order_retry_max`).
- Still unreadable after 3 attempts → **pause ALL ATO** (CE + PE) + warn + **JAGRAN**.
- If a retry **succeeds** after failure in the same cycle → **continue monitoring** (no operator Resume) + **JAGRAN info** alert: book was unreadable, now recovered.
- Operator **Resume** still required for feed-related / manual pauses (Q16, Q23).

### 6.4 CE / PE independence (Q28)

- One side paused (broker fail, manual intervention pause) → **other side continues**.

---

## 7. Manual Dhan intervention matrix

| # | Scenario | Decision |
|---|----------|----------|
| 26A | Idle; manual buy **correct** protect strike before breach | Adopt + warn → **holding**, exit-only, no second BUY |
| 26A+ | Idle; manual buy **more** lots than registered (correct strike) | Adopt **registered ATO lots only**; warn excess on book (Q72 **A**) |
| 26A− | Idle; manual buy **fewer** lots than registered | **Ignore** partial manual; at breach BUY **registered** lots book-first (Q73 **C**) |
| 26B | Breach; you + algo buy; book shows full qty | Filled — no retry |
| 26C | Manual buy **wrong** strike (≠ registered protect) | **Ignore** — monitor registered protect only (Q50); never touch stray legs |
| 26D | Holding; manual sell **all** | **Pause affected side** + warn |
| 31 | Holding; manual sell **partial** | **Pause affected side** + warn |
| 34A | Wrong-strike pause; `/resume` with wrong leg still on book | **Resume** + warn — monitor **registered strike only**; **do not touch** other legs |
| 34B | Wrong leg **closed**; `/resume` | Normal armed behaviour |
| 40 | Orphan old protect after new register | Warn at confirm; ignore for algo |

**Never:** Auto-close, merge, or “fix” legs the operator did not register for ATO.

---

## 8. Data & market failures

| Event | UAT + prod (Q16) |
|-------|------------------|
| Stale NIFTY cache | **Auto-pause ATO** |
| Circuit freeze / untradeable spot | **Same as stale** — pause (Q23, Q64) |
| DRISHTI feed recovery | **Auto-resume at 09:25** if feed healthy and pause was feed-owned (Q63 **C**); **operator Pause** stays manual |

---

## 9. Pause / resume

| Command | Effect |
|---------|--------|
| **Pause** | Stop all monitoring and orders; open legs stay on Dhan |
| **Resume** | Clear **side halt** for manual-intervention pauses (26D, 31, order fail); re-evaluate from **current** NIFTY; if breached and idle → BUY per Q32C **only if protect not already at broker** (Q55, Q56) |
| Read-only commands | OK while paused (status, legs, funds) |

---

## 10. Config reference (`telegram/bots/kavach/params.json`)

Planned section `ato_operator` (names illustrative — implement as structured JSON):

| Key | Default | Purpose |
|-----|---------|---------|
| `lot_size` | 65 | NIFTY qty per lot |
| `ato_step` | 50 | Auto protect distance |
| `strike_presets_ce` | [500, 1000] | CE only: sell **+** offset |
| `strike_presets_pe` | [100, 500] | PE only: sell **−** offset (display as −100, −500) |
| `order_retry_max` | 3 | Broker order + book validation |
| `cleanup_retry_max` | 3 | Post-Complete verify |
| `soft_cap_first_warn_cycles` | 3 | Per side per day |
| `soft_cap_repeat_every_cycles` | 2 | Warn again at 5, 7, 9… |
| `poll_interval_seconds` | 1 | ATO tick (existing) |

---

## 11. Telegram message catalog (planned)

| Trigger | Channel | Message gist |
|---------|---------|----------------|
| Register blocked (armed) | KAVACH | Complete Batman first |
| Invalid strike at confirm | KAVACH | Strike not available for this expiry |
| Custom strike confirm warn | KAVACH | Custom ATO — reduced hedge / economy profile |
| Cleanup fail 3× | KAVACH + JAGRAN | Cleanup failed — fix before register |
| Cleanup OK | KAVACH | Verified — starting registration… |
| Monitor-only breach | KAVACH | CE/PE breach — no order (0 lots) |
| Soft cap cycle | KAVACH | Side hit N cycles today — chop warning |
| Order fail after retries | KAVACH + JAGRAN | Check Dhan portal; side paused |
| Position book fail | KAVACH + JAGRAN | All ATO paused |
| Batman Complete | KAVACH | List open ATO legs + cleanup checklist |
| ATO BUY/SELL success | KAVACH only | Normal trade notify (not JAGRAN) |

---

## 12. SARANSH reporting (Q25, Q49, Q58)

- Tag deployments using **custom protect strike** (typed in wizard) as **Custom ATO / economy profile** (Q49 **A**).
- Preset offsets (+500/+1000/−100/−500) are **normal** — no economy tag.
- **Display (Q58 C):** show tag in **deployment summary header** and in a **dedicated ATO / economy section** of every SARANSH run (manual + EOD).
- ATO Cycle view shows sell trigger vs protect strike vs lots explicitly (planned).

---

## 13. Economy chop test recipe (Gate 5 / UAT)

**CE example:**

| Field | Example |
|-------|---------|
| CE sell | 24,500 CE |
| CE protect | 26,000 CE (+1,500 above sell) |
| ATO lots | 1 |
| Entry buffer | 0 |
| Exit buffer | 5 |
| Monitor | CE only or both |

**PE mirror (same logic, opposite direction):**

| Field | Example |
|-------|---------|
| PE sell | 24,000 PE |
| PE protect | 22,500 PE (−1,500 below sell) |
| ATO lots | 1 |
| Entry buffer | 0 |
| Exit buffer | 5 |
| Monitor | PE only or both |

**Prove either side:** breach alert → mock BUY at protect → retrace → mock SELL → soft cap → SARANSH economy tag.

---

## 13b. CE / PE symmetry contract (mandatory)

Every rule stated with a **CE example** applies to **PE** with mirrored direction.  
One behaviour → one implementation path per side — **never CE-only**.

### Direction mirror

| Concept | CE | PE |
|---------|----|----|
| Breach | NIFTY **≥** sell + entry buffer | NIFTY **≤** sell − entry buffer |
| Auto protect | sell **+** 50 | sell **−** 50 |
| Presets | **+500**, **+1000** only | **−100**, **−500** only (no + on PE) |
| Retrace exit | spot **≤** sell − exit buffer | spot **≥** sell + exit buffer |
| Direction warn | protect ≤ sell | protect ≥ sell |

### Same rule both sides

Custom lots · invalid strike block · book validate + 3 retries · soft cap per side · monitor-only alert · manual-leg matrix · Batman qty drift (pause **that side**) · order-fail pause **that side** · wrong-strike pause **that side**.

**Monitoring mode (Q46):** Only **registered + monitored** sides are checked for wrong protect legs. Example: monitor **CE only** → stray PE long on Dhan is **ignored** (other position, 34A). Symmetric: monitor **PE only** → stray CE ignored.

### PE manual-leg examples (mirror §7)

| Scenario | PE example | Decision |
|----------|------------|----------|
| 26A | Manual 22,500 PE before breach (registered) | Adopt; exit-only |
| 26C | Manual 23,500 PE (≠ registered 22,500) | Ignore — monitor 22,500 only |
| 26D / 31 | Manual sell all/partial on 22,500 PE | Pause PE |
| 40 | Orphan 22,500 PE; new register 21,000 PE | Warn; manage 21,000 only |

### Code symmetry audit (2026-06-20)

| Area | Symmetric today? | Gap |
|------|------------------|-----|
| Breach / retrace loop | ✅ | — |
| Cycles per side | ✅ | Change hard max → soft warn |
| `pe_ato_lots` / `ce_ato_lots` | ✅ | — |
| Wizard PE + CE blocks | ✅ | Presets not built **either** side |
| Startup scan adopt | ✅ | Mid-session matrix not built |
| `_check_managed_qty_mismatch` | ⚠️ | Pauses **whole** algo — needs **per-side** (Q41) |
| Per-side halt flag | ❌ | Needed for 26C, 31, order fail |
| Monitor-only Telegram | ❌ | Both sides |
| Complete-first register | ❌ | UAT + prod |

---

## 14b. Registered-lots edge cases + Quick Tune (Q79–Q98) — locked 2026-07-15

### Registered lots (Q79–Q82)

| Q | Rule |
|---|------|
| Q79 **A** | Retrace SELL = **registered ATO lots only**; never sell excess manual qty |
| Q80 **A** | Partial manual ignored (Q73) + breach still on → BUY remainder **book-first** |
| Q81 **A** | Exact manual buy of registered lots → adopt holding / exit-only; no second BUY |
| Q82 **A** | Operator adds lots while holding → ignore excess; exit scope stays registered |

### Quick Tune / ATO Configuration (Q83–Q98)

| Q | Rule |
|---|------|
| Q83 **C** / Q84 **A** | v1 Quick Tune = **entry + exit buffers only**; lots/strikes need Complete → Register |
| Q85 **A** | Allowed while holding; new buffer applies on **next tick** |
| Q86 / Q88 | **Skipped** — N/A for buffers-only v1 |
| Q87 **A** | Lots ↓ while holding (Complete path) → registered smaller; ignore broker excess |
| Q89 **A** | Entry buffer while holding: **recalc only**; stay holding; new buffer after retrace |
| Q90 **C** | Invoke via **`/ato_tune`** and `/ato_status` / menu buttons |
| Q91 **A** | Menu label = **ATO Configuration** |
| Q92 **C** | Side pick: CE only \| PE only \| Tune both \| Cancel |
| Q93 **A** | Every step: current value + **Keep current** |
| Q94 **C** | v1 order = **Entry → Exit** per side |
| Q95 **C** | Confirm = summary + **warnings** + Apply |
| Q96 **C** | Strike UI (future / Complete): register keyboards + highlight current |
| Q97 **A** | Both sides: all CE buffers then all PE → one summary |
| Q98 **B** | Not armed → “Register first” + point to `/register` |

**Code:** `bat_telegram/bots/kavach/ato_configuration_wizard.py` · `apply_ato_buffer_patch` in `bot.py`

---

## 14. Scenario index (all discovery Q&A)

| Q | Topic | Answer |
|---|-------|--------|
| 1 | Capital / UAT | Operator owns capital; UAT mirrors prod |
| 2 | Far OTM weak hedge | Warn; operator accepts |
| 3 | ATO lots | Operator choice; warn on mismatch |
| 4 | Partial hedge at breach | No extra alert |
| 5 | Cycle limit | Soft cap warn; no stop |
| 6 | Invalid strike | Block confirm |
| 7 | Already breached at confirm | Buy immediately |
| 8 | Order validation | Local book; 3 retries; pause side |
| 9 | Soft cap N | 3 per side/day (config) |
| 10 | Expiry day | Same rules to 15:15 |
| 11 | Holiday | Auto-skip ATO |
| 12 | BUY fail | Same as SELL path |
| 13 | Partial fill | Whole lots only; retry remainder |
| 14–16 | Stale feed | Auto-pause UAT + prod |
| 17 | Complete with open ATO | Allow + strong warn |
| 18–22 | Adoption qty | Broker truth at register |
| 23 | Circuit | Pause like stale |
| 24 | Re-register | **Complete first** → cleanup → auto wizard |
| 25 | SARANSH | Economy tag |
| 26A–E | Manual legs | Matrix §7 |
| 27 | Presets | CE: Auto +500 +1000 · PE: Auto −100 −500 · custom |
| 41 | Batman qty drift | Pause + warn + JAGRAN → Complete → re-register |
| 42 | Wizard cancel | Safe idle |
| 43 | Monitor-only soft cap | Breach counts |
| 44 | PE presets | Minus only on PE; plus only on CE |
| 45 | Strike master | Same UAT + prod |
| 46 | CE-only monitor + stray PE | **Ignore** — other position (34A) |
| 28 | Both sides | Independent |
| 29 | 0 lots breach | Telegram alert |
| 30 | Position source | Announce at register start |
| 31–32 | Manual exit / resume | Pause; resume+BUY if breached |
| 33 | Book unreadable | Pause all |
| 34A–B | Wrong strike resume | C then A |
| 35 | Quiet hours breach | Alert anyway |
| 36–40 | Complete / cleanup / orphan | §3 |

---

## 15. Implementation gap matrix (code vs plan)

| Area | Status | Notes |
|------|--------|-------|
| Register while armed | **Done** | Block → Complete first |
| Post-Complete auto-wizard | **Done** | After verify pass |
| Cleanup retry | **Done** | `cleanup_retry_max` from params |
| Complete open ATO list | **Done** | `open_ato_protect_lines` |
| Strike validation | **Done** | Block confirm if not in master |
| Strike presets | **Done** | CE +500/+1000, PE −100/−500 |
| Position source line | **Done** | `register_preamble()` |
| `max_cycles` hard stop | **Done** | Replaced with soft warn |
| Order validation | **Done** | Book-first + retry → side halt |
| Manual leg sync | **Done** | §7 mid-session sync in `ato_protection.py` |
| Monitor-only breach | **Done** | `ATO_MONITOR_BREACH` event |
| SARANSH economy tag | **Done** | Deployment `profile` + SARANSH summary section (Q58) |
| Position book retry | **Done** | `core/ato_position_book.py` (Q62) |
| Resume + side halt | **Done** | `clear_resumable_side_halts` + Q32C re-entry |
| Orphan leg warn | **Done** | `core/ato_orphan_legs.py` at confirm (Q59) |
| format_cleanup auto wizard | **Done** | `auto_register` flag |

---

## 16. Batman leg drift & wizard cancel (Q41–Q45)

### 16.1 Batman qty below registered (Q41)

| Event | Action |
|-------|--------|
| Broker Batman leg qty **below** registered managed qty (manual partial close on Dhan) | **Pause that side** (or all — same as A) + **warn** + **JAGRAN** |
| Recovery | **Batman Complete** → cleanup → re-register |

### 16.2 Wizard cancel after auto-start (Q42)

| Event | Action |
|-------|--------|
| Complete OK → wizard auto-started → operator **Cancel** / timeout | **No armed deployment** — safe idle; run register again when ready |

### 16.3 Monitor-only & soft cap (Q43)

- Breach alerts with **0 ATO lots** **count** toward per-side soft-cap warnings (chop exposure without premium).

### 16.4 PE vs CE preset buttons (Q44)

| Side | Preset buttons | Never show |
|------|----------------|------------|
| **CE** | Auto · **+500** · **+1000** · Custom | Minus offsets on CE |
| **PE** | Auto · **−100** · **−500** · Custom | Plus offsets on PE |

PE protect is always on the **downside** of PE sell (lower strike).

### 16.5 Strike existence check (Q45)

- **UAT and prod** use the **same** instrument master (Dhan / cached live series).
- Invalid strike for expiry → **block Confirm** in both modes.

---

## 17. Scenario index (additions Q41–Q45)

| Q | Topic | Answer |
|---|-------|--------|
| 41 | Batman leg qty drop on Dhan | Pause side + warn + JAGRAN → Complete → re-register |
| 42 | Cancel wizard after Complete | Safe idle — no armed Batman |
| 43 | Monitor-only vs soft cap | Breach alerts **count** toward chop warnings |
| 44 | PE/CE presets | CE: plus only · PE: minus only |
| 45 | Strike validation UAT | Same master as prod |

---

## 18. Implementation status (2026-06-20)

| Area | Status | Notes |
|------|--------|-------|
| `ato_operator` params | Done | `telegram/bots/kavach/params.json` |
| Register gate (armed block) | Done | `wizard_entry` + cleanup-fail block |
| Complete → retry → auto-wizard | Done | `run_cleanup_with_retries` |
| CE/PE strike presets | Done | `register_wizard.py` keyboards |
| Protect strike validation | Done | `core/strike_validation.py` at confirm |
| Per-side halt flags | Done | `core/ato_side_state.py` |
| Soft cap (warn-only) | Done | `modules/ato_protection.py` — no hard stop |
| Monitor-only breach alert | Done | `Event.ATO_MONITOR_BREACH` + Telegram |
| Order book retry → side halt | Done | `core/ato_book_validation.py` |
| Batman qty drift per-side | Done | CE/PE independent in `_check_managed_qty_mismatch` |
| Manual leg sync matrix (§7) | Done | `core/ato_manual_leg_sync.py` + poll hook |
| SARANSH economy tag UI | Done | `bat_telegram/bots/saransh/bot.py` Q58 |
| Position book 3× retry | Done | Q62 `core/ato_position_book.py` |
| Resume clears side halt | Done | Q55 `clear_resumable_side_halts` |
| ATO Configuration / Quick Tune | Done | Q83–Q98 — buffers-only wizard |
| UAT E2E verification | Run when JWT+bots up | Agent script |

**Confidence: 99%** on business rules. Remaining work is engineering verification, not operator Q&A.

---

*Last updated: 2026-07-15 — Quick Tune coded (Q79–Q98 locked).*
