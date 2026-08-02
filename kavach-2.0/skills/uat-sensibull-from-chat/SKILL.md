---
name: uat-sensibull-from-chat
description: Read Sensibull screenshot in Cursor chat; write uat/deployed_positions/positions.json (cursor_chat) for KAVACH UAT Register without OCR.
---

# UAT Sensibull from chat

## Triggers
- UAT POSITIONS + screenshot
- fetch positions from screenshot
- June expiry / 09 Jun + image
- @uat-sensibull-from-chat

## Workflow
1. Read image: B/S, expiry, strike, CE/PE, lots, price for **all 8 legs** (6 BUY + 2 SELL).
2. Map to JSON: exactly 1 PE SELL, 1 CE SELL, 6 BUY (at least 1 PE BUY and 1 CE BUY). Do **not** pre-mark Core BUY.
3. expiry_date ISO (09 Jun -> 2026-06-09).
4. Run: scripts/write_uat_chat_positions.py --stdin or --json
5. Run: validate_fixture.py on uat/deployed_positions/positions.json
6. Run: scripts/quick_uat_positions_gate.py (no bot restart)
7. Tell user: tap Register in KAVACH UAT — pick **Core PE BUY** then **Core CE BUY**; SELL steps unchanged. Armed book stays 4 core legs.

See UAT_CHAT_POSITIONS.md for copy-paste shortcut.

**Note:** Sensibull OCR fallback still expects a classic 4-leg image. Prefer `cursor_chat` 8-leg book for daily UAT.
