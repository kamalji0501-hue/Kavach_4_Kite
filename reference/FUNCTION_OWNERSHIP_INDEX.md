# Function Ownership Index

Purpose: Quick lookup of key functions and their owning files, to reduce full-codebase scans.

## Loader and Bot Config

| Function        | File                   | Responsibility                                             |
| --------------- | ---------------------- | ---------------------------------------------------------- |
| load_bot_config | bat_telegram/loader.py | Resolve bot token/chat/params from token.env + params.json |
| reload_all      | bat_telegram/loader.py | Clear loader cache for full re-read                        |
| bot_names       | bat_telegram/loader.py | Return supported bot mapping names                         |

## Broker and Token Lifecycle

| Function           | File                | Responsibility                               |
| ------------------ | ------------------- | -------------------------------------------- |
| connect_with_token | core/broker.py      | Create broker session from Dhan access token |
| hot_reload_token   | core/broker.py      | Apply fresh token without process restart    |
| needs_reauth       | core/broker.py      | Token age guard for reauth warnings          |
| get_nifty_ltp      | core/broker.py      | NIFTY price fetch shortcut                   |
| get_live_pnl       | core/broker.py      | Runtime MTM/PnL fetch                        |
| save               | core/token_store.py | Persist access token timestamped to disk     |
| load               | core/token_store.py | Restore token and saved timestamp            |
| is_expired         | core/token_store.py | Token expiry check against TTL               |

## Core Runtime Utilities

| Function           | File              | Responsibility                             |
| ------------------ | ----------------- | ------------------------------------------ |
| subscribe          | core/event_bus.py | Register callback for system events        |
| publish            | core/event_bus.py | Emit event with payload to subscribers     |
| get                | core/state.py     | Read runtime state key                     |
| set                | core/state.py     | Write runtime state key with optional save |
| load (classmethod) | core/config.py    | Load and validate settings config          |
| get                | core/config.py    | Dot-path config value lookup               |

## Scheduler and Module Lifecycle

| Function              | File                  | Responsibility                       |
| --------------------- | --------------------- | ------------------------------------ |
| start                 | bot/algo_scheduler.py | Start scheduler background loop      |
| stop                  | bot/algo_scheduler.py | Stop scheduler loop                  |
| handle_time_selection | bot/algo_scheduler.py | Apply user-selected daily start time |
| stop_algo             | bot/algo_scheduler.py | Manually stop algo modules           |
| resume_algo           | bot/algo_scheduler.py | Resume modules when allowed          |

## Telegram Bot Entry Points

| Function          | File                             | Responsibility                                      |
| ----------------- | -------------------------------- | --------------------------------------------------- |
| build_application | bat_telegram/bots/drishti/bot.py | Build DRISHTI Telegram app with config and handlers |
| build_application | bat_telegram/bots/kavach/bot.py  | Build KAVACH Telegram app with config and handlers  |
| build_application | bat_telegram/bots/lakshmi/bot.py | Build LAKSHMI Telegram app with config and handlers |

## How To Use This File

1. Locate the requested behavior domain.
2. Jump directly to owning file/function first.
3. Use reference/TECHNICAL_CHANGE_INDEX.md to identify required sidecar updates.
4. Update tracker/log/context artifacts in the same session.
