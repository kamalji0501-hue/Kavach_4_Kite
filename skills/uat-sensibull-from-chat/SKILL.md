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
1. Read image: B/S, expiry, strike, CE/PE, lots, price for all 4 legs.
2. Map to JSON leg order: pe_sell, pe_buy, ce_buy, ce_sell (PE strikes asc, CE strikes asc).
3. expiry_date ISO (09 Jun -> 2026-06-09).
4. Run: scripts/write_uat_chat_positions.py --stdin or --json
5. Run: validate_fixture.py on uat/deployed_positions/positions.json
6. Run: scripts/quick_uat_positions_gate.py (no bot restart)
7. Tell user: tap Register in KAVACH UAT.

See UAT_CHAT_POSITIONS.md for copy-paste shortcut.
