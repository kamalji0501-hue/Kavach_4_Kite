# KAVACH / ATO — Tomorrow Handoff (2026-06-20 session)

**Purpose:** Read this **first** in tomorrow’s new Cursor chat.  
**Operator:** Rahul — voice-driven collaboration; imperfect transcript OK.  
**Topic:** Picture-perfect KAVACH (कवच / Coverage) core ATO module — discovery + implementation.  
**Paused:** End of day 2026-06-20 — system restart + Cursor update planned.

---

## 1. Copy-paste prompt for new chat

```
Read docs/KAVACH_TOMORROW_HANDOFF.md and docs/KAVACH_OPEN_QUESTIONS.md first.
Then docs/KAVACH_ATO_OPERATOR_RULES.md (operator bible).

We are building KAVACH as the picture-perfect ATO module. Q1–Q46 are locked.
Implementation ~60% done. Tomorrow: answer Q47–Q54 (or "go with all recommended"),
then continue coding — priority likely manual-leg sync matrix §7.

Voice-to-text framework applies: intent over words; Kavach=Coverage, Drishti, Dhan, etc.
Execute autonomously: pytest, bot checks, UAT E2E when relevant. UAT primary on laptop.
```

---

## 2. Session arc (what we did today)

### Phase A — Discovery (earlier in conversation)
- **46 operator Q&A batches** covering register, Complete, ATO, CE/PE symmetry, economy/chop, manual Dhan legs, soft cap, etc.
- Authoritative doc: **`docs/KAVACH_ATO_OPERATOR_RULES.md`**
- Updated: `bat_telegram/bots/kavach/KAVACH_CONTEXT.md`, `telegram/design/kavach_design.md`, `GATE5_RUNBOOK.md`, `AGENTS.md`

### Phase B — Implementation (operator said “go”)
Core behavioural changes landed; **not** full §7 manual-leg matrix yet.

---

## 3. What is coded (Done)

| Area | Files / notes |
|------|----------------|
| Operator tunables | `telegram/bots/kavach/params.json` → `ato_operator` section |
| Config helpers | `core/ato_operator_config.py`, `core/strike_validation.py`, `core/ato_side_state.py`, `core/ato_book_validation.py` |
| Register gate | Armed Batman blocks `/register`; cleanup-fail blocks too (`bat_telegram/bots/kavach/bot.py`) |
| Complete flow | Retry cleanup ≤3, list open ATO legs, auto-start register wizard (`core/batman_cleanup.py`, `bot.py`) |
| Wizard presets | CE +500/+1000, PE −100/−500 (`register_wizard.py`) |
| Strike validation | Block confirm if strike not in instrument master |
| UAT source line | `core/environment_display.py` → `register_preamble()` |
| **ATO engine** | `modules/ato_protection.py`: soft cap (warn only), per-side halt, monitor-only breach event, book retry → side halt, Batman qty drift per-side |
| Events | `Event.ATO_MONITOR_BREACH` in `core/event_bus.py` |
| Telegram | Soft-cap + monitor-only breach pushes (`bot.py` subscriptions) |
| State reset | Side halt flags cleared on Batman Complete (`_state_reset`) |
| Tests | `test_ato_operator_config.py`, `test_ato_side_state.py`, `TestATOSoftCap`, startup scan fixes, `MockBroker` updates positions on order |
| Docs gap matrix | §15 + §18 in operator bible updated |

### ATO engine behaviour (locked + implemented)

- **Soft cap:** warn at 3, 5, 7… per side/day — **never** hard-stop cycling
- **Per-side halt:** CE and PE independent (`ato.ce_side_halted` / `ato.pe_side_halted`)
- **Qty drift:** halt **that side** only (not whole algo)
- **Monitor-only (0 ATO lots):** Telegram alert + counts toward soft cap
- **Orders:** book-first validation, `order_retry_max` (3), then halt side + JAGRAN path
- **Register:** blocked while armed; Complete → verify → auto wizard

---

## 4. What is NOT coded yet (Pending)

| Area | Priority | Notes |
|------|----------|-------|
| **Manual leg sync matrix §7** | **High** | 26A–26D, 31, 34A–B mid-session poll adoption |
| **Wrong-strike pause (26C)** | High | Detect + pause side |
| **SARANSH economy tag UI** | Medium | `profile` in deployment JSON only; display not wired |
| **Q33 pause ALL** on unreadable book | Medium | May need explicit path in `_check_breach` |
| **UAT E2E verification** | After code | Needs fresh DRISHTI JWT + bots running |
| **Auto-wizard PTB state** | Verify live | `_set_register_conversation_state` after Complete |

---

## 5. Open questions — operator must answer tomorrow

**File:** `docs/KAVACH_OPEN_QUESTIONS.md`

| # | Topic | Recommended |
|---|-------|-------------|
| Q47 | Qty drift vs retrace | A |
| Q48 | Book lag / retry timing | A |
| Q49 | SARANSH economy tag scope | C |
| Q50 | Wrong-strike manual buy (26C) | A (confirm bible) |
| Q51 | Manual full exit while holding | A (confirm bible) |
| Q52 | Resume with wrong leg (34A) | A (confirm bible) |
| Q53 | Unreadable position book | A (confirm bible) |
| Q54 | Next coding priority | A (manual-leg matrix) |

**Fast clear:** `Accept bible for Q50–Q53. Q47 A, Q48 A, Q49 C, Q54 A.`  
Or: **Go with all recommended.**

---

## 6. Test status (end of session)

| Suite | Result |
|-------|--------|
| ATO-related (40 tests) | **PASS** — `TestATOSoftCap`, `TestATOStartupScan`, `TestATOProtection`, `test_ato_*` |
| Full pytest (excl. UAT daily matrix) | ~10 failures — **pre-existing** env issues (`data/dev/` path, logging paths, etc.) |
| UAT daily matrix (`test_uat_daily_matrix.py`) | Fails off-hours: expired JWT, bots STOPPED, OCR — expected without live session |

**Commands for tomorrow verify:**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ato_operator_config.py tests/test_ato_side_state.py tests/test_modules.py::TestATOSoftCap tests/test_modules.py::TestATOStartupScan tests/test_modules.py::TestATOProtection -q
.venv\Scripts\python.exe -m ruff check core modules bat_telegram
.venv\Scripts\python.exe -m pytest tests -q --ignore=tests/test_uat_daily_matrix.py
```

After JWT refresh + bots up:

```powershell
.venv\Scripts\python.exe scripts\run_uat_e2e_verification.py
```

---

## 7. Key file map

| Purpose | Path |
|---------|------|
| Operator bible (locked Q1–Q46) | `docs/KAVACH_ATO_OPERATOR_RULES.md` |
| **Open questions (Q47–Q54)** | `docs/KAVACH_OPEN_QUESTIONS.md` |
| **This handoff** | `docs/KAVACH_TOMORROW_HANDOFF.md` |
| ATO engine | `modules/ato_protection.py` |
| KAVACH bot + wizard | `bat_telegram/bots/kavach/bot.py`, `register_wizard.py` |
| Params / tunables | `telegram/bots/kavach/params.json` |
| Gate 5 economy test | `GATE5_RUNBOOK.md` |
| Agent playbook | `AGENTS.md`, `UAT_E2E_AGENT.md` |

---

## 8. Architecture reminders (do not break)

- **Four OS processes:** DRISHTI, KAVACH, JAGRAN, SARANSH — do not merge
- **Start order:** DRISHTI → KAVACH → JAGRAN → SARANSH
- **UAT primary** on laptop; shadow broker + Sensibull/Cursor chat book
- **DRISHTI** owns JWT + NIFTY cache; KAVACH reads cache only for ATO
- **Lots vs qty:** UI = lots, broker = qty (NIFTY lot size **65**)
- **Do not touch without explicit ask:** DRISHTI Health/Ping/Token Status handlers

---

## 9. Voice collaboration framework (locked for this project)

Operator communicates by voice; transcription errors expected.

**Interpret intent, not literal words:**
- Coverage / Cavage → **KAVACH**
- Dristi → **DRISHTI**
- Done / Than → **Dhan**
- Auto → **ATO** (in trading context)

**Confidence model:**
- \>90% → proceed, no interrupt
- 70–90% → proceed, state assumption briefly
- \<70% → ask focused question (only if capital/risk/execution impact)

**Classify each voice note:** confirmed requirement | likely | future | brainstorming

---

## 10. Tomorrow agenda (suggested)

1. Operator answers Q47–Q54 (voice OK)
2. Deep-dive remaining §7 scenarios not yet in numbered Q format (see open questions file §Future batches)
3. Implement manual-leg sync matrix (if Q54 = A)
4. SARANSH economy tag (if Q49 locked)
5. pytest + UAT E2E when bots/JWT ready
6. Update `KAVACH_ATO_OPERATOR_RULES.md` §15 gap matrix as items complete

---

## 11. Transcript reference

Full agent transcript (pre/post summary):  
`agent-transcripts/0809dc98-85fe-4e98-9f52-0543d71c6d3d.jsonl`

---

*Good night — resume tomorrow from Q47–Q54 and manual-leg implementation.*
