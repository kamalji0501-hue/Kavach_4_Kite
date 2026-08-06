# GO Bot

Independent Telegram bot — **not** part of Batman Phase 1.

Places/manages NIFTY option orders:

- **Multi-leg (Batman 2.0):** enter NIFTY level → preview 8 legs → Confirm (entry only)
- **Single-leg:** Buy CE/PE with fixed SL/Target, trailing, and operator Exit

## Quick start

1. Create a Telegram bot via @BotFather.
2. Copy secrets:
   ```bash
   cp GO/telegram/bots/go/token.env.example GO/telegram/bots/go/token.env
   ```
3. Fill `GO_BOT_TOKEN` and `GO_CHAT_ID`.
4. Ensure DRISHTI has a valid Dhan JWT (shared `access_token.json`).
5. Start: `Execution/Start\ Bots/start\ Go.sh`
6. Stop: `Execution/Stop\ Bots/stop\ Go.sh`

See `GO_CONTEXT.md` for locked design.
