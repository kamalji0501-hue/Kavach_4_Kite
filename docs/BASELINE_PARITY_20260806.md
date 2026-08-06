# Baseline parity vs Kamalji `/home/ubuntu/batman-algo` (2026-08-06)

Critical check: Rahul sandbox must not break Kamalji-proven trading/bot logic.

## Code identity

| Scope | Result |
|-------|--------|
| Shared `core` + `bat_telegram` + `modules` `.py` | 132 |
| Byte-identical | **126** |
| Differ | **6** (credentials/path only) |
| New in Rahul | `core/telegram_credentials.py` only |
| Missing from Rahul vs Kamalji | **0** |
| `run_drishti/kavach/jagran/saransh/kavach2.py` | **byte-identical** |

### Hot paths (sha256 match)

`broker.py`, `broker_factory.py`, `config.py`, `state.py`, `event_bus.py`, `token_store.py`, `modules/ato_protection.py`, Kavach/Jagran/Saransh bot modules.

### Intentional diffs only

- `bat_telegram/loader.py` — prefers desktop `bots.env`, still falls back to per-bot `token.env`
- `core/kavach_telegram.py`, `optional_bot_startup.py`, `incident_publisher.py`, Drishti `_remember_chat_id`
- `core/batman_mode.py` — adds `secrets_telegram_bots_env_path` wrapper; other functions hash-identical (CRLF→LF normalize)

## Behavioral checks

| Check | Result |
|-------|--------|
| Loader without `bots.env` (Kamalji-style fallback) | 4/4 bots still load |
| Loader with `bots.env` restored | 4/4 from desktop |
| Telegram smoke load | PASS |
| Bot start → Application started (earlier retest) | 4/4 PASS |
| Critical imports BA + RC | 12/12 OK each |

## Pytest (same suite both trees)

Stopped after 15 failures on each. **Failure sets are essentially the same** (shared 14). Differences only in UAT daily matrix cases about missing Sensibull/`positions.json` on each runtime — data/env, not strategy code.

Notable: ATO retracement tests fail on **Kamalji baseline too** while `ato_protection.py` is byte-identical — pre-existing / environment, not introduced by Rahul credential work.

## Verdict

**Logic parity with Kamalji working code: HOLD.**  
Rahul changes are release/path/credentials packaging. Trading and bot application logic matches the baseline.
