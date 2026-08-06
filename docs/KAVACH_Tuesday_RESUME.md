# KAVACH / ATO — Tuesday Resume Pack (Telegram back)

> **Superseded for coding status (2026-07-15):** Q79–Q98 locked · Quick Tune **coded**.
> **Resume next chat from:** `NEW_CHAT_HANDOFF.md` / `CONTEXT.md` §26.


**Purpose:** Read this **first** when Telegram is reachable again.  
**Mode until live Telegram:** **NO CODING** — design + Q&A only (`docs/KAVACH_OPEN_QUESTIONS.md` **Q79–Q98**).  
**Operator:** Rahul — voice OK; Kavach = Coverage.  
**Handoff (2026-06-21):** `NEW_CHAT_HANDOFF.md` — Q1–Q78 locked; resume Coverage questions next.

---

## 1. Copy-paste for new Cursor chat (Tuesday)

```
Read docs/KAVACH_Tuesday_RESUME.md and docs/KAVACH_OPEN_QUESTIONS.md first.
Q1–Q62 locked and coded. Answer Q63+ (or "go with all recommended").
Telegram is back — run live checks before any new coding:
  phase1_bot_check → run_uat_e2e_verification → Gate 5 spot checks.
No new ATO code unless live test proves a bug. Voice framework applies. UAT primary.
```

**Shorter voice command to agent:**

> Read KAVACH Tuesday resume. Telegram is back — run live checks.

---

## 2. What is DONE (coded + pytest)

| Theme | Status |
|-------|--------|
| Register gate, Complete, cleanup, auto-wizard | Done |
| CE/PE presets, strike validation, position source line | Done |
| Soft cap (warn only), per-side halt, monitor-only breach | Done |
| Order book-first + 3 retries → side halt | Done |
| Batman qty drift per-side | Done |
| Manual-leg §7 (26A, 26C ignore, 26D, 31, Q33/Q62 retry) | Done |
| Resume clears side halt + Q32C re-entry (Q55–Q56) | Done |
| SARANSH economy section + custom profile JSON (Q58, Q49 A) | Done |
| Orphan warn at Confirm (Q59) | Done |
| Adopt exit qty = registered ATO only (Q60) | Done |

**Key files:** `modules/ato_protection.py`, `core/ato_manual_leg_sync.py`, `core/ato_position_book.py`, `core/ato_orphan_legs.py`, `core/ato_side_state.py`, `kavach-2.0/bat_telegram/bots/kavach2/bot.py`, `bat_telegram/bots/saransh/bot.py`

**Operator bible:** `docs/KAVACH_ATO_OPERATOR_RULES.md` (Q1–Q62 locked)

---

## 3. What is NOT done (blocked on Telegram / live UAT)

| Item | Why pending |
|------|-------------|
| `scripts/phase1_bot_check.py` live PASS | Needs `api.telegram.org` |
| `scripts/run_uat_e2e_verification.py` | Register/callbacks in chat |
| Gate 5 economy chop walkthrough | Operator + live SARANSH/KAVACH |
| Manual-leg spot checks (26A, stray leg, resume) | Dhan UAT book + Telegram |
| DRISHTI NIFTY cache freshness in session | Market + feed when testing |

**Do not treat Telegram timeout as a code bug** (India ban / VPN routing).

---

## 4. Tuesday command sequence (operator → agent)

Run in order after VPN + Telegram app work on phone:

| Step | You say | Agent runs |
|------|---------|------------|
| 1 | **Telegram path OK — run live checks** | `bot_status.py all` → `audit_bot_tokens.py` → `phase1_bot_check.py` |
| 2 | *(if step 1 PASS)* | `run_uat_e2e_verification.py` (fix loop max 4 if fail) |
| 3 | **Gate 5 economy test** | Walkthrough per `GATE5_RUNBOOK.md` + SARANSH economy tag |
| 4 | **Answer Q63+** or **go with all recommended** | Lock in open questions file → only then new code if needed |

**Refresh JWT if expired:** send token to DRISHTI or agent saves to `data/access_token.json` (never paste in chat if avoidable).

**Restart bots if needed:**

```powershell
Execution\Phase 1 Stop All Robots.bat
Execution\Phase 1 Start All Robots.bat
Execution\Show Bot Status.bat
```

---

## 5. Design-only work NOW (no coding)

**Primary:** **`docs/KAVACH_ATO_CONFIGURATION_DESIGN.md`** — ATO Configuration menu, UI flow, Q79–Q98.

Answer by voice:

- Q79–Q82 registered-lots edge cases  
- Q83–Q90 Quick Tune behaviour on Apply  
- Q91–Q98 Telegram UI (side picker, 4 questions, Confirm)

One line: **Q79–Q82 all A** then **Q83–Q98** per question or **go with all recommended**.

---

## 6. pytest already green (no Telegram)

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ato_position_book.py tests/test_ato_manual_leg_sync.py tests/test_ato_orphan_legs.py tests/test_ato_side_state.py tests/test_saransh_economy_profile.py tests/test_modules.py::TestATOManualLegSync tests/test_modules.py::TestATOProtection tests/test_modules.py::TestATOStartupScan tests/test_modules.py::TestATOSoftCap -q
```

---

## 7. Architecture reminders

- Four OS processes: DRISHTI → KAVACH → JAGRAN → SARANSH  
- UAT primary; shadow broker + Sensibull book  
- Lots in UI, qty on broker (65)  
- Do not touch DRISHTI Health/Ping/Token Status without explicit ask  

---

*Paused for Telegram — resume Tuesday with live checks before any new code.*
