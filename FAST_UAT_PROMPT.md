# FAST UAT — copy-paste prompt (attach Sensibull screenshot)

Use this **every time** you only need a new positions book. **No bot restart.**

---

## Copy into Cursor Agent (attach screenshot in same message)

```
@FAST_UAT_PROMPT.md @uat-sensibull-from-chat

FAST UAT — update book only. Execute yourself. No bot restart.

1. Read attached Sensibull screenshot: expiry + 4 legs (B/S, strike, CE/PE, lots, price).
2. Write uat/deployed_positions/positions.json:
   - source: cursor_chat
   - leg order: pe_sell, pe_buy, ce_buy, ce_sell
3. Save screenshot as uat/deployed_positions/sensibull_chat_latest.png
4. Run: .venv\Scripts\python.exe scripts\quick_uat_positions_gate.py
5. Reply exactly:
   OK: uat\deployed_positions\positions.json
   Expiry: ...
   Legs: (4-line table)
   >>> Tap Register in KAVACH now.

Rules:
- Do NOT stop/start bots. Do NOT run daily test suite.
- If KAVACH STOPPED only → start KAVACH bat, not full Phase 1 restart.
- If I say FULL UAT → use daily prompt in UAT_CHAT_POSITIONS.md instead.
```

---

## Your steps after agent says OK

1. Open **KAVACH** Telegram → tap **Register**
2. Complete wizard → confirm

Log should show: `UAT register: using cursor_chat positions.json (skip OCR)`

---

## One-liner (voice)

> FAST UAT screenshot. No restart. quick_uat_positions_gate. Tap Register when OK.

---

## Script only (positions.json already written)

```
Execution\Quick UAT Positions.bat
```

Or: `.venv\Scripts\python.exe scripts\quick_uat_positions_gate.py`
