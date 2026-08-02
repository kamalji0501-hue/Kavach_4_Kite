# FAST UAT — copy-paste prompt (attach Sensibull screenshot)

Use this **every time** you only need a new positions book. **No bot restart.**

---

## Copy into Cursor Agent (attach screenshot in same message)

```
@FAST_UAT_PROMPT.md @uat-sensibull-from-chat

FAST UAT — update book only. Execute yourself. No bot restart.

1. Read attached Sensibull screenshot: expiry + **8 legs** (6 BUY + 2 SELL; B/S, strike, CE/PE, lots, price).
2. Write uat/deployed_positions/positions.json:
   - source: cursor_chat
   - 6 BUY + 1 PE SELL + 1 CE SELL (Core BUY not pre-marked)
3. Save screenshot as uat/deployed_positions/sensibull_chat_latest.png
4. Run: .venv\Scripts\python.exe scripts\quick_uat_positions_gate.py
5. Reply exactly:
   OK: uat\deployed_positions\positions.json
   Expiry: ...
   Legs: (8-line table)
   >>> Tap Register in KAVACH now (pick Core PE BUY, then Core CE BUY).

Rules:
- Do NOT stop/start bots. Do NOT run daily test suite.
- If KAVACH STOPPED only → start KAVACH bat, not full Phase 1 restart.
- If I say FULL UAT → use daily prompt in UAT_CHAT_POSITIONS.md instead.
```

---

## Your steps after agent says OK

1. Open **KAVACH** Telegram → tap **Register**
2. Pick **Core PE BUY** from all PE buys → PE SELL (unchanged) → **Core CE BUY** from all CE buys → CE SELL → confirm
3. Armed Batman deployment remains **4 core legs** (extra buys stay in the book only)

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
