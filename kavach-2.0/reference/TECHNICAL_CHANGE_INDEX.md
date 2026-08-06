# Technical Change Index

Purpose: Fast routing map for where to edit when a specific behavior changes.

Use this file to avoid scanning the entire codebase during rapid iteration.

## Core Ownership Map

| Domain                   | Primary File(s)                                   | What It Owns                                             |
| ------------------------ | ------------------------------------------------- | -------------------------------------------------------- |
| Broker integration       | core/broker.py, core/token_store.py               | Dhan API access, token apply/reload/persistence          |
| Shared state             | core/state.py                                     | Runtime flags, lifecycle keys, cross-module state        |
| Event routing            | core/event_bus.py                                 | Pub/sub contracts for module and bot notifications       |
| Scheduling               | bot/algo_scheduler.py, core/config.py             | Start/stop timing, daily prompts, scheduler policies     |
| ATO logic                | modules/ato_protection.py                         | Breach detection, ATO cycles, startup scan/retrace exits |
| Trailing                 | modules/profit_trailing.py                        | Expiry-day trailing behavior and related state keys      |
| Position monitoring      | modules/position_monitor.py                       | MTM polling and monitor events                           |
| Emergency exit           | modules/emergency_exit.py                         | Force close behavior and safety flows                    |
| Telegram config loader   | bat_telegram/loader.py                            | token.env + params.json resolution and known bot mapping |
| DRISHTI bot              | bat_telegram/bots/drishti/bot.py                  | token ops, health prompts, infra command UX              |
| KAVACH bot               | kavach-2.0/bat_telegram/bots/kavach2/bot.py                   | trading command UX, deploy/exit/pause/resume flows       |
| LAKSHMI bot              | bat_telegram/bots/lakshmi/bot.py                  | pnl/mtm reporting and alerting UX                        |
| SANCHALAK config mapping | telegram/bots/sanchalak/*, bat_telegram/loader.py | global-control bot token/params mapping templates        |
| SARANSH bot              | bat_telegram/bots/saransh/bot.py, run_saransh.py  | ATO Cycle UI, daily summary, EOD 15:35, session status   |
| SARANSH reporting feed   | core/saransh_reporting.py, core/ato_cycle_feed.py | JSONL ingest, compact table, XLSX builder                |
| SARANSH session sync     | core/saransh_session_sync.py                      | KAVACH register/complete hooks, auto restart             |
| SARANSH config mapping   | telegram/bots/saransh/*, bat_telegram/loader.py   | summary bot token/params mapping templates               |
| Runtime wiring           | main.py                                           | Active bot startup, shared dependencies, loop lifecycle  |

## Change Routing Matrix

| If You Change                      | Always Check                                                                                     | Usually Update                                    |
| ---------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| Token handling or expiry prompts   | bat_telegram/bots/drishti/bot.py, core/token_store.py                                            | core/broker.py, telegram/bots/drishti/params.json |
| ATO trigger/retrace behavior       | modules/ato_protection.py                                                                        | DESIGN.md, tests/test_modules.py                  |
| Deploy wizard fields or validation | kavach-2.0/bat_telegram/bots/kavach2/bot.py                                                                  | telegram/design/kavach_design.md, DESIGN.md       |
| PnL summary schema                 | bat_telegram/bots/saransh/bot.py, core/saransh_reporting.py                                      | SARANSH_IMPLEMENTATION_STATUS.md, saransh_design.md |
| ATO cycle feed / point impact      | modules/ato_protection.py, core/ato_cycle_feed.py, core/saransh_reporting.py                     | tests/test_ato_cycle_feed.py, GATE5_RUNBOOK.md    |
| SARANSH session on Batman Complete | core/saransh_session_sync.py, kavach-2.0/bat_telegram/bots/kavach2/bot.py                                    | SARANSH_IMPLEMENTATION_STATUS.md                  |
| PnL summary schema (LAKSHMI)       | bat_telegram/bots/lakshmi/bot.py                                                                 | DESIGN.md, IMPLEMENTATION_TRACKER.md              |
| New bot config mapping             | bat_telegram/loader.py, telegram/bots/<name>/token.env.example, telegram/bots/<name>/params.json | CONTEXT.md, IMPLEMENTATION_TRACKER.md             |
| Incident routing policy            | telegram/design/architecture.md, JAGRAN_ERROR_MATRIX.md                                          | IMPLEMENTATION_TRACKER.md, SESSION_CAPTURE_LOG.md |
| Global control policy              | DESIGN.md, OPEN_QUESTIONS.md                                                                     | IMPLEMENTATION_TRACKER.md, CONTEXT.md             |
| Runtime activation/deactivation    | main.py                                                                                          | CONTEXT.md, IMPLEMENTATION_TRACKER.md             |

## Mandatory Sidecar Updates After Any Meaningful Change

1. IMPLEMENTATION_TRACKER.md
2. IMPLEMENTATION_TRACKER.csv
3. SESSION_CAPTURE_LOG.md
4. CONTEXT.md (if architecture/scope/status changed)
5. reference/DECISION_REGISTER.md (if a new design decision was made)
6. reference/DISCUSSION_CAPTURE.md (session summary)

## Quick Start (When a New Request Arrives)

1. Identify domain in Core Ownership Map.
2. Open primary file(s) first.
3. Check Change Routing Matrix for linked files.
4. Make smallest safe edit set.
5. Apply mandatory sidecar updates.
