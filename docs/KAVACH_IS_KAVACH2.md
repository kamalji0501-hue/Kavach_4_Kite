# Kavach = Kavach 2.0 only

Classic Kavach (`run_kavach.py`, `bat_telegram.bots.kavach`) has been **removed**.

| What | Where |
|------|--------|
| Code / runner | `run_kavach2.py` → `kavach-2.0/` + `bat_telegram.bots.kavach2` |
| Telegram bot | Classic identity `@kavach_batmanbot` via `KAVACH_BOT_TOKEN` |
| Secrets path | `telegram/bots/kavach/token.env` |
| systemd (Rahul VPS) | `batman-kavach2.service` (classic `batman-kavach.service` unused) |

`get_bot_credentials("kavach2")` reads `KAVACH_*` first, then legacy `KAVACH2_*`.
