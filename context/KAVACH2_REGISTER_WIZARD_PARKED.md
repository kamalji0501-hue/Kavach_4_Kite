# Parked: KAVACH 2.0 Register after Batman Complete (resume from here)

> **Status:** DONE for core fix — re-verify in Telegram when you return; continue UAT Register from PE BUY.  
> **Saved:** 2026-07-19 (~12:30 UTC / ~18:00 IST)  
> **Project:** `DEV Batman Algo` / `kavach-2.0`  
> **Chat:** Skip Enable PE wizard

---

## User problem (why we stopped)

After **Batman Complete** on Kavach 2.0, Telegram showed:

- Register wizard → **“Enable PE side coverage?”** with **Enable PE / Skip PE / Cancel**
- Clicking any button did **nothing** (stuck)

User asked to **remove that prompt** and jump straight to the **later window** = **Select PE BUY leg**.

---

## Root causes (fixed)

1. **Enable PE / Enable CE screens** were still the first Register steps.
2. After Batman Complete auto-started Register, conversation state was written to the wrong place (`user_data[(name,chat,user)]`). On PTB, live state lives on `ConversationHandler._conversations` — so callbacks never matched and buttons appeared dead.

---

## What was changed

| Area | Change |
|------|--------|
| `kavach-2.0/core/wizard_plan.py` | Plan skips `pe_intent` / `ce_intent`; both sides max **12** questions (was 19 with intents). Starts at `pe_buy` / `ce_buy`. |
| `kavach-2.0/bat_telegram/bots/kavach2/register_wizard.py` | `begin_register_leg_pick()` — auto-detect PE/CE from open LONG legs; start at PE BUY (or CE BUY if no PE). Legacy `wizard_pe_intent` redirects into that. |
| `kavach-2.0/bat_telegram/bots/kavach2/bot.py` | `_wizard_fetch_step1` calls `begin_register_leg_pick`. `_set_register_conversation_state` sets `ConversationHandler._conversations[key]` for handler name `kavach2_register`. |
| `kavach-2.0/core/position_scope.py` | `filter_positions_by_side` falls back to symbol suffix (`…PE` / `…CE`) if `opt_type` missing. |
| Tests | `tests/test_wizard_plan.py`, PE-intent cases in `tests/test_kavach_scenarios.py` (kavach2). |

**Expected flow now:** Batman Complete → cleanup verified → **Select your PE BUY leg** (buttons work).

---

## Runtime at park time

- Bot: `kavach-2.0/run_kavach2.py` (UAT / virtual)
- Restarted successfully after fix (`Application started`)
- Ignore any **old** “Enable PE” message still visible in Telegram chat history — run **Batman Complete** or **Register** again for the new UI

---

## Resume checklist (next session)

1. In Telegram Kavach 2.0: **Batman Complete** (or **Register**) → confirm first step is **PE BUY** (not Enable PE).
2. Tap a PE BUY leg → confirm wizard continues (PE SELL → ATO strike → buffers → …).
3. If buttons still dead: check logs for `KAVACH2: register conversation state set` / `ConversationHandler not found` (logger `batman.kavach2` may not always land in hourly `kavach2_*.log` — check process stdout / `all.log`).
4. Optional cleanup later: remove unused `pe_intent_keyboard` / `WIZARD_PE_INTENT` imports from kavach2 bot if still unused; sync docs in `KAVACH_CONTEXT.md` flow diagram.
5. Do **not** reopen AWS always-on unless asked — that stays in [VPS_CONTEXT.md](VPS_CONTEXT.md) “Resume later — AWS always-on”.

---

## Key paths

```
kavach-2.0/bat_telegram/bots/kavach2/bot.py          # Batman Complete → _wizard_fetch_step1
kavach-2.0/bat_telegram/bots/kavach2/register_wizard.py  # begin_register_leg_pick, build_wizard_handler
kavach-2.0/core/wizard_plan.py
kavach-2.0/core/position_scope.py
```

Conversation handler name: **`kavach2_register`**.
