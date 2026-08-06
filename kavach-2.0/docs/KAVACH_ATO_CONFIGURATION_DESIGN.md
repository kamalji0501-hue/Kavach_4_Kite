# KAVACH — ATO Configuration (Quick Tune) Design Pack

**Purpose:** Spec + resume context for mid-session ATO buffer tune.  
**Status:** **Q79–Q98 locked** (2026-07-15) · **v1 coded** (buffers only)  
**Operator bible:** `docs/KAVACH_ATO_OPERATOR_RULES.md` §14b · **Q&A:** `docs/KAVACH_OPEN_QUESTIONS.md`

---

## 1. What shipped (v1)

| Item | Detail |
|------|--------|
| Menu | **ATO Configuration** (`kav_menu:ato_tune`) |
| Command | `/ato_tune` |
| Status | Button on `/ato_status` (`atc:start`) |
| Scope | **Entry + exit buffers only** (CE/PE) |
| Order | Entry → Exit; CE then PE when both (Q94 C / Q97 A) |
| Holding | Allowed; next tick / next cycle rules (Q85 A / Q89 A) |
| Not armed | “Register first” (Q98 B) |
| Confirm | Summary + warnings + Apply (Q95 C) |
| Module | `kavach-2.0/bat_telegram/bots/kavach2/ato_configuration_wizard.py` |
| Apply | `bot.apply_ato_buffer_patch` — patches JSON + state buffers; **does not** clear holding |

Lots / protect strikes still require **Batman Complete → Register**.

---

## 2. Telegram flow (locked)

```
Main menu /ato_tune / ATO Status button
  └─ [ ATO Configuration ]
        │
        ▼
  Side: CE only | PE only | Tune both | Cancel
        │
        ▼
  Per side: Entry buffer → Exit buffer
  (Keep current | Predefined | Custom)
        │
        ▼
  Summary old→new + warnings → Apply | Cancel
```

---

## 3. Locked answers Q79–Q98

See table in `docs/KAVACH_ATO_OPERATOR_RULES.md` §14b and full text in `docs/KAVACH_OPEN_QUESTIONS.md`.

**Skipped:** Q86, Q88 (N/A buffers-only v1).

---

## 4. Apply behaviour (v1)

| Change | While idle | While holding |
|--------|------------|---------------|
| Exit buffer | Next tick | Next tick (Q85 A) |
| Entry buffer | Next tick | Stay holding; new buffer after retrace (Q89 A) |
| Lots / strike | Not in Quick Tune | Complete → Register |

---

## 5. Round 2 (later)

1. Wider Quick Tune (lots / strike) if operator expands Q84  
2. Wireframes for paused / side-halted tune  
3. SARANSH economy tag refresh on lots change  
4. Full Apply matrix for lot ↑↓ mid-hold (Q86/Q87 revisit)

---

## 6. Related files

| File | Role |
|------|------|
| `ato_configuration_wizard.py` | ConversationHandler |
| `bot.py` `apply_ato_buffer_patch` | Persist + live state |
| `tests/test_ato_configuration_wizard.py` | Unit tests |
| `docs/KAVACH_OPEN_QUESTIONS.md` | Full Q text |

---

*Implemented 2026-07-15 after operator locked Q79–Q98.*
