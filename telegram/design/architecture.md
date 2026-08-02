# Batman v3 — Telegram Subsystem Architecture
## Design Doc | Last updated: 2026-05-17 | Status: ACTIVE-SCOPE UPDATED (five-bot runtime interlinks)

> Active scope (current phase): DRISHTI, KAVACH, SANCHALAK, SARANSH, JAGRAN.
> LAKSHMI, PRABHAT MUKTI, and RATRIPAL follow-up work are intentionally out of active coding scope until explicitly resumed.

---

## 1. Core Philosophy

> "Everything should be independent. Everything should be managed carefully and separately.
>  It should not disturb others. Everything needs to be dynamic."

- Every bot is a **fully self-contained unit** — own token, own parameters, own code folder
- Changing one bot's token, parameters, or code has **zero impact** on the other two bots
- Each file has a single responsibility — token file holds only tokens, params file holds only parameters
- All parameters are **hot-reloadable** — no restart needed after any config change

---

## 1a. Process Architecture (LOCKED — 2026-04-04)

> "Everything will be controlled via Telegram from mobile. Rahul never touches the server console once deployed."

### Deployment Model

| Aspect              | Decision                                                                                |
| ------------------- | --------------------------------------------------------------------------------------- |
| **Where it runs**   | VPS (Virtual Private Server) — 24 × 7 uptime                                            |
| **How it starts**   | `python main.py` — single command, starts everything                                    |
| **Process model**   | **Single Python process** — `asyncio` event loop, all tasks run in parallel             |
| **Control surface** | 100% Telegram — Rahul sends commands from mobile, never needs shell access after launch |
| **Broker auth**     | Rahul sends the daily Dhan access token to DRISHTI bot → hot-reloaded into broker       |

### Why Single Process (asyncio parallelism)

- **ATO loop** runs as an asyncio background task — fires orders even while Rahul is checking `/pnl`
- **All 3 Telegram bots** run as asyncio tasks — each responds independently
- **AlgoScheduler, ProfitTrailing, Overnight Hedge** — all asyncio tasks, no blocking
- **EventBus** is in-process — instant relay from algo events → KAVACH/DRISHTI/LAKSHMI notifications
- **Broker singleton** is shared across all tasks — no IPC, no duplication
- No inter-process communication needed — everything in one memory space

### asyncio Task Map (single process)

```
python main.py
│
├── asyncio.run(batman_main())
│   │
│   ├── Task: DRISHTI bot  ← polling Telegram — token updates, health, algo prompts
│   ├── Task: KAVACH bot   ← polling Telegram — deploy wizard, ATO control, trading commands
│   ├── Task: LAKSHMI bot  ← polling Telegram — MTM alerts, /pnl, EOD P&L
│   │
│   ├── Task: AtoProtection.run_loop()        ← ATO breach detection + order placement
│   ├── Task: AlgoScheduler.run_loop()         ← daily start-time prompt sender, EOD reminder
│   ├── Task: ProfitTrailing.run_loop()        ← trailing stop monitoring
│   ├── Task: PositionMonitor.run_loop()       ← position-level monitoring
│   └── Task: OvernightHedge.run_loop()        ← overnight hedge logic
│
└── Shared singletons (passed to all tasks):
    ├── BatmanBroker         ← one broker instance, DRISHTI hot-updates token
    ├── StateManager         ← shared state (armed/paused/positions)
    └── EventBus             ← algo events → bot notifications
```

### Bot Responsibility Split (LOCKED)

| Bot         | Owns                                                                             | Does NOT own                    |
| ----------- | -------------------------------------------------------------------------------- | ------------------------------- |
| **DRISHTI** | Access token delivery, broker health, AlgoScheduler daily prompts, system alerts | Trading commands, P&L           |
| **KAVACH**  | All trading commands (`/register`, `/exit`, `/pause`, etc.), ATO notifications   | P&L reporting, token management |
| **LAKSHMI** | `/pnl`, MTM alerts, profit target alerts, EOD P&L summary                        | Trading commands, token/health  |

### AlgoScheduler Daily Prompts → DRISHTI (LOCKED)

The 9:00 AM "what time do you want to start the algo today?" time-picker and the EOD "mark batman complete?" reminder **move out of AlgoScheduler** and become DRISHTI responsibilities.

- AlgoScheduler still owns the **logic** (waiting, timing, auto-start)
- DRISHTI owns the **Telegram interaction** (sending the prompt, receiving the reply)
- Communication: DRISHTI calls `algo_scheduler.set_start_time(hhmm)` directly (same process)

### /pnl — Exclusively LAKSHMI (LOCKED)

`/pnl` belongs to LAKSHMI only. KAVACH does not implement `/pnl`. Modular design: each bot owns one domain.

### JAGRAN Incident Channel (LOCKED — 2026-05-02)

JAGRAN is a dedicated high-priority incident bot/channel for immediate attention notifications. It is additive to the 3-bot domain split and does not change ownership boundaries.

- JAGRAN receives only critical/major incidents.
- Mandatory publishers: DRISHTI, KAVACH, RATRIPAL, PRABHAT MUKTI.
- Error events are dual-published: source-domain bot/channel and JAGRAN.
- Not all source errors are sent to JAGRAN; only immediate-action scenarios are eligible.
- Per-source scenario allowlists are design-controlled and will be finalized progressively.
- Routine informational messages stay in the source-domain bot.
- Repeated alerts must be deduplicated and reported as periodic "still failing" updates.
- Recovery transitions must be published to JAGRAN for incidents previously sent there.

Standard high-priority error template:
- "{part} has thrown an error at {timestamp}. Error message: {error_message}"

---

## 2. Bot Roster

| #   | Name        | Hindi | Telegram API Token Env Var | Responsibility                                       |
| --- | ----------- | ----- | -------------------------- | ---------------------------------------------------- |
| 1   | **DRISHTI** | दृष्टि   | `DRISHTI_BOT_TOKEN`        | Infrastructure health + daily Dhan access token mgmt |
| 2   | **KAVACH**  | कवच   | `KAVACH_BOT_TOKEN`         | Core positions, ATO protection, deployment commands  |
| 3   | **LAKSHMI** | लक्ष्मी  | `LAKSHMI_BOT_TOKEN`        | MTM alerts, profit targets, P&L reporting            |

Each bot has its own separate BotFather API token and its own chat. They run independently.

JAGRAN follows the same isolation principle: independent token/chat and independent notification sound profile for critical incidents.

---

## 3. Folder Structure (as built)

```
telegram/
│
├── __init__.py                      ← subsystem entry point + quick-start usage docs
├── loader.py                        ← shared config loader — one loader serves all 3 bots
│
├── bots/
│   │
│   ├── drishti/
│   │   ├── token.env                ← DRISHTI_BOT_TOKEN + DRISHTI_CHAT_ID  (gitignored)
│   │   ├── token.env.example        ← safe template — copy this to token.env  (committed)
│   │   ├── params.json              ← all DRISHTI parameters  (committed, no secrets)
│   │   └── __init__.py
│   │
│   ├── kavach/
│   │   ├── token.env                ← KAVACH_BOT_TOKEN + KAVACH_CHAT_ID  (gitignored)
│   │   ├── token.env.example        ← safe template  (committed)
│   │   ├── params.json              ← all KAVACH parameters  (committed, no secrets)
│   │   └── __init__.py
│   │
│   └── lakshmi/
│       ├── token.env                ← LAKSHMI_BOT_TOKEN + LAKSHMI_CHAT_ID  (gitignored)
│       ├── token.env.example        ← safe template  (committed)
│       ├── params.json              ← all LAKSHMI parameters  (committed, no secrets)
│       └── __init__.py
│
├── design/
│   ├── architecture.md              ← this file (system overview + index)
│   ├── drishti_design.md            ← DRISHTI detailed behaviour design (locked 2026-03-20)
│   ├── kavach_design.md             ← KAVACH detailed behaviour design (locked 2026-04-04)
│   ├── lakshmi_design.md            ← LAKSHMI design (stub — pending)
│   ├── drishti_flow.html            ← DRISHTI flow diagrams (3 Mermaid diagrams)
│   ├── kavach_flow.html             ← KAVACH flow diagram (pending)
│   └── lakshmi_flow.html            ← LAKSHMI flow diagram (pending)
│
└── flowcharts/                      ← additional flowcharts (placeholder)
```

---

## 4. The Two-File Rule

Each bot has exactly **two operational config files**. This separation is intentional and permanent — never collapse them into one.

### File 1 — `token.env`  (Token file — GITIGNORED)

```ini
# Example: telegram/bots/drishti/token.env
DRISHTI_BOT_TOKEN=<ENTER_DRISHTI_BOT_TOKEN>
DRISHTI_CHAT_ID=<ENTER_DRISHTI_CHAT_ID>
```

| Property     | Rule                                                               |
| ------------ | ------------------------------------------------------------------ |
| Contents     | Telegram API token + chat ID ONLY. Nothing else.                   |
| Git          | **NEVER committed.** In `.gitignore` via `**/token.env` catch-all. |
| Template     | Copy from `token.env.example` when setting up.                     |
| When to edit | Only when your Telegram bot token changes.                         |
| Risk on edit | Zero impact on params. Zero impact on other bots.                  |

### File 2 — `params.json`  (Parameters file — COMMITTED)

```json
{
  "_bot": "DRISHTI (दृष्टि)",
  "enabled": true,
  "quiet_hours": { "start": "08:00", "end": "23:30", "timezone": "Asia/Kolkata" },
  "retry": { "max_attempts": 3, "delay_seconds": 5, "backoff_multiplier": 2 },
  ...
}
```

| Property     | Rule                                                                            |
| ------------ | ------------------------------------------------------------------------------- |
| Contents     | All tunable settings — timings, thresholds, flags, retries. No secrets.         |
| Git          | **Safe to commit.** Full version history of all parameter changes.              |
| When to edit | Changing reminder times, thresholds, retry counts, enabling/disabling features. |
| Risk on edit | Zero impact on token. Zero impact on other bots.                                |

---

## 5. Why Two Files Instead of One

| Scenario                                | Without separation                                                 | With two-file rule                                   |
| --------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------- |
| Update KAVACH token                     | Must open a file containing all settings — risk of accidental edit | Open `kavach/token.env` — only the token is in there |
| Change DRISHTI reminder times           | Must open file containing token — risk of accidental exposure      | Open `drishti/params.json` — no secrets in sight     |
| LAKSHMI threshold change corrupts token | Possible if same file                                              | Impossible — different files                         |
| Commit parameter history to git         | Blocked — secrets mixed in                                         | Safe — `params.json` has zero secrets                |
| Rotate one bot's token                  | Must re-verify nothing else changed                                | One key in one file — nothing else can be affected   |

---

## 6. Token Update Workflow

When you receive a new Telegram API token from BotFather:

```
Step 1:  Open  telegram/bots/<name>/token.env
Step 2:  Replace the value of <NAME>_BOT_TOKEN with the new token
Step 3:  Save the file
Step 4:  The system hot-reloads automatically — NO RESTART NEEDED
```

That is the entire procedure. `params.json` is untouched. Other bots are untouched.

---

## 7. Parameter Update Workflow

When you want to change a timing, threshold, or behaviour:

```
Step 1:  Open  telegram/bots/<name>/params.json
Step 2:  Edit the relevant value
Step 3:  Save the file
Step 4:  Call  load_bot_config("<name>", reload_params=True)  — NO RESTART NEEDED
```

Token is untouched. Other bots are untouched.

---

## 8. Shared Loader (`telegram/loader.py`)

One loader serves all three bots. Key design points:

- Uses `dotenv_values()` (not `load_dotenv`) — reads `token.env` in **isolation without polluting `os.environ`**
- In-process cache (`_CACHE`) avoids re-reading files on every call
- Selective hot-reload: re-read only the file that changed

```python
from telegram.loader import load_bot_config

# First load (cold — reads both files):
cfg = load_bot_config("drishti")
cfg.bot_token    # → resolved API token string
cfg.chat_id      # → resolved chat ID string
cfg.params       # → full params.json dict

# Token updated in token.env → hot-reload token only:
cfg = load_bot_config("drishti", reload_token=True)

# Param changed in params.json → hot-reload params only:
cfg = load_bot_config("kavach", reload_params=True)

# Full reload (both files):
cfg = load_bot_config("lakshmi", reload_token=True, reload_params=True)
```

**Secrets resolution order** (first match wins):
1. `token.env` file — preferred for local development
2. System environment variable — used on CI / Docker / production servers

This means you can deploy to a server, set `DRISHTI_BOT_TOKEN` as an OS env var, and skip the `token.env` file entirely — same code works both ways.

---

## 9. Per-Bot Parameters Reference

> **Full detailed behaviour design for each bot is in its own file:**
> - DRISHTI: [drishti_design.md](drishti_design.md) — locked 2026-03-20
> - KAVACH:  [kavach_design.md](kavach_design.md)  — locked 2026-04-04
> - LAKSHMI: [lakshmi_design.md](lakshmi_design.md) — pending

---

### DRISHTI — Infrastructure Health + Access Token Management

→ Full design: [drishti_design.md](drishti_design.md)

| `params.json` group | What it controls                                          | Key values (defaults)                         |
| ------------------- | --------------------------------------------------------- | --------------------------------------------- |
| `quiet_hours`       | Outbound reminder messages suppressed outside this window | `08:00` – `23:30` IST. Bot accepts 24/7.      |
| `token_reminders`   | Scheduled reminders when Dhan access token is expired     | `09:00`, `15:30`, `23:00` IST (weekdays only) |
| `health_check`      | Proactive health reports during trading window            | `08:45`–`15:45`, every `3600s`                |
| `retry`             | Retry config for broker/LTP API calls                     | 3 attempts, 5s delay, ×2 backoff              |
| `gift_nifty`        | GIFT Nifty symbol candidates + fallback source            | `["GIFT NIFTY", "NIFTYBEES"]`, yfinance       |
| `alerts`            | Immediate health alerts (no quiet hours, always fire)     | broker/LTP/module failures, 60min expiry warn |

**Two alert types in DRISHTI:**
- **TYPE 1 — Scheduled token reminder:** fires on NSE weekdays if Dhan access token is expired or never set. Suppressed if token updated < 24h ago. Respects quiet hours.
- **TYPE 2 — Immediate health alert:** fires any time when broker API fails, NIFTY LTP fetch fails, GIFT Nifty fails, or any module crashes. No quiet hours. No suppression.

→ **Full detailed design:** [drishti_design.md](drishti_design.md)
→ **Flow diagrams:** [drishti_flow.html](drishti_flow.html)

---

### KAVACH — Core Positions, ATO Protection, Deployment Wizard

→ **Full detailed design:** [kavach_design.md](kavach_design.md)

| `params.json` group | What it controls                                       | Key values (defaults)                       |
| ------------------- | ------------------------------------------------------ | ------------------------------------------- |
| `quiet_hours`       | Proactive notifications suppressed outside this window | `08:00` – `23:30` IST. Commands work 24/7.  |
| `commands`          | Toggle individual bot commands on/off without restart  | All enabled by default                      |
| `confirmations`     | Which commands require yes/no reply before executing   | `emergency_exit`, `batman_done` (30s TTL)   |
| `notifications`     | Which trade events KAVACH announces via Telegram       | ATO trigger/exit, deploy, batman_done, algo |
| `retry`             | Retry config for order placement API calls             | 3 attempts, 2s delay, ×1.5 backoff          |
| `rate_limit`        | Prevent accidental command spamming                    | 10 commands/min, 5s cooldown                |
| `deploy_wizard`     | Deployment wizard settings                             | `ato_step: 50`, `timeout_seconds: 120`      |

→ **Full detailed design:** [kavach_design.md](kavach_design.md)

**Key design decisions (summary):**
- `/register` is the canonical deployment command (retired aliases are removed)
- File-present rule: one JSON in `data/deployments/` = Batman armed. Empty folder = not armed.
- `/batman_complete` = halt monitoring, archive deployment state, and reset for next cycle.
- ATO step = 50 (configurable). PE_ATO = PE_sell − 50. CE_ATO = CE_sell + 50. User confirms, never overrides.
- No ratio validation — Rahul's confirmation is the authority.
- Audit log: `data/deployments/deploy_log.jsonl` — append-only, all events recorded.

##### KAVACH Core Responsibilities

| #   | Responsibility                                                                                | When active                              |
| --- | --------------------------------------------------------------------------------------------- | ---------------------------------------- |
| 1   | **Deployment Wizard** — interactive 4-leg selection, ATO auto-calc, confirmation, file write  | On `/register` command                   |
| 2   | **Batman Done** — halt all Batman monitoring, leave positions untouched on broker             | On `/batman_done` command                |
| 3   | **ATO status** — report current ATO state per side (triggered/idle, cycle counts)             | On `/ato` command                        |
| 4   | **Emergency exit** — close all positions immediately at market                                | On `/exit` command (yes/no confirmation) |
| 5   | **Algo control** — pause/resume the ATO monitoring loop                                       | On `/stop_algo`, `/resume_algo`          |
| 6   | **Trade event notifications** — ATO triggered, ATO retrace exit, deploy confirmed, limits hit | Proactive — quiet hours apply            |

---

→ **Full detailed design, wizard state machine, file schemas:** [kavach_design.md](kavach_design.md)

---

### LAKSHMI — MTM Alerts, Profit Targets, P&L Reporting

→ **Full design:** [lakshmi_design.md](lakshmi_design.md) — **PENDING** (params defined, behaviour not yet designed)

| `params.json` group | What it controls                                     | Key values (defaults)                   |
| ------------------- | ---------------------------------------------------- | --------------------------------------- |
| `quiet_hours`       | Scheduled P&L reports suppressed outside this window | `08:00` – `23:30` IST                   |
| `mtm`               | MTM loss alert — fires IMMEDIATELY (no quiet hours)  | threshold `−₹5,000`, interval 300s      |
| `profit_target`     | Alert when cumulative MTM crosses profit target      | target `₹50,000`                        |
| `trailing`          | Trailing stop thresholds for alert notifications     | hard stop `−₹8,000`, activate `₹12,000` |
| `pnl_report`        | End-of-day P&L summary after market close            | `15:35` IST, includes positions         |
| `retry`             | Retry config for MTM / balance fetch calls           | 3 attempts, 3s delay, ×2 backoff        |
| `alert_format`      | Control verbosity of alert messages                  | show legs, hide greeks, `₹` symbol      |

---

## 10. Security Rules

| Rule                | Detail                                                               |
| ------------------- | -------------------------------------------------------------------- |
| `**/token.env`      | Blocked by `.gitignore` catch-all. Can never be committed.           |
| `token.env.example` | Contains placeholder values only — safe to commit.                   |
| `params.json`       | Zero secrets — safe to commit, version-control, review.              |
| `dotenv_values()`   | Reads token file without writing to `os.environ` — no env pollution. |
| Blast radius        | Any mistake is confined to one bot's one file.                       |

---

## 11. Adding a Fourth Bot (future)

Only 5 steps required — no other file needs changing:

1. Create `telegram/bots/<name>/token.env`  (copy from any existing `token.env.example`)
2. Create `telegram/bots/<name>/token.env.example`  (template with placeholder values)
3. Create `telegram/bots/<name>/params.json`  (model after existing params files)
4. Create `telegram/bots/<name>/__init__.py`  (one-line docstring)
5. Add `"<name>"` to `_KNOWN_BOTS` set in `telegram/loader.py`

Done. The loader, gitignore catch-all, and rest of the system require zero changes.

---

## 12. Build Status

| Component                    | File                                | Status                           |
| ---------------------------- | ----------------------------------- | -------------------------------- |
| Subsystem entry              | `telegram/__init__.py`              | ✓ Built                          |
| Shared loader                | `telegram/loader.py`                | ✓ Built                          |
| DRISHTI token file           | `bots/drishti/token.env`            | ✓ Built (fill in real token)     |
| DRISHTI template             | `bots/drishti/token.env.example`    | ✓ Built                          |
| DRISHTI parameters           | `bots/drishti/params.json`          | ✓ Built                          |
| KAVACH token file            | `bots/kavach/token.env`             | ✓ Built (fill in real token)     |
| KAVACH template              | `bots/kavach/token.env.example`     | ✓ Built                          |
| KAVACH parameters            | `bots/kavach/params.json`           | ✓ Updated 2026-04-04             |
| LAKSHMI token file           | `bots/lakshmi/token.env`            | ✓ Built (fill in real token)     |
| LAKSHMI template             | `bots/lakshmi/token.env.example`    | ✓ Built                          |
| LAKSHMI parameters           | `bots/lakshmi/params.json`          | ✓ Built                          |
| Git protection               | `.gitignore` (`**/token.env`)       | ✓ Built                          |
| DRISHTI bot logic            | `bots/drishti/bot.py`               | ⏳ Next — Phase 0                 |
| KAVACH bot entry point       | `bots/kavach/bot.py`                | ⏳ Pending — design locked        |
| KAVACH deploy wizard         | `bots/kavach/deploy_wizard.py`      | ⏳ Pending — design locked        |
| LAKSHMI bot logic            | `bots/lakshmi/bot.py`               | ⏳ Pending                        |
| Deployment active folder     | `data/deployments/`                 | ⏳ Pending (create + .gitkeep)    |
| Deployment archive folder    | `data/deployments/archive/`         | ⏳ Pending (create + .gitkeep)    |
| Deployment audit log         | `data/deployments/deploy_log.jsonl` | ⏳ Created on first /deploy run   |
| ATO module — read deployment | `modules/ato_protection.py`         | ⏳ Pending — read deployment file |
| DRISHTI flow diagram         | `telegram/design/drishti_flow.html` | ✓ Built                          |
| KAVACH flow diagram          | `telegram/design/kavach_flow.html`  | ⏳ Pending                        |
| LAKSHMI flow diagram         | `telegram/design/lakshmi_flow.html` | ⏳ Pending                        |

### Files to Create (Coding Phase — in priority order)

```
Priority 1 — KAVACH Deployment Wizard:
  telegram/bots/kavach/deploy_wizard.py     ← ConversationHandler (4 states + summary + confirm)
  telegram/bots/kavach/bot.py               ← KAVACH async entry point, all command registrations
  data/deployments/.gitkeep                 ← ensure folder tracked in git
  data/deployments/archive/.gitkeep         ← ensure archive folder tracked in git

Priority 2 — ATO module integration:
  modules/ato_protection.py                 ← read deployment file for protect symbols + strikes
                                               replace hardcoded/state values with file read

Priority 3 — DRISHTI bot logic:
  telegram/bots/drishti/bot.py              ← 3 async coroutines (reminder, monitor, listener)
                                               /health, /ping, token collection + validation

Priority 4 — LAKSHMI bot logic:
  telegram/bots/lakshmi/bot.py               ← MTM alerts, profit target, EOD P&L, /pnl
```
