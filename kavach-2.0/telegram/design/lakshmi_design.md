# LAKSHMI (लक्ष्मी) — Detailed Design
## Bot 3 | MTM Alerts, Profit Targets, P&L Reporting
## Design Doc | Status: DESIGN PENDING — params defined, behaviour not yet designed

---

## Role

LAKSHMI is the **P&L and alert bot**. It watches the live MTM (mark-to-market) value of Batman positions and alerts Rahul when loss thresholds are hit, when profit targets are reached, and sends an end-of-day P&L summary.

> **Process model (LOCKED 2026-04-04):** LAKSHMI runs as an asyncio task inside a single `python main.py` process on the VPS, alongside DRISHTI, KAVACH, and all algo modules.

> **`/pnl` is exclusively LAKSHMI's command.** KAVACH does not implement `/pnl`. Modular design: each bot owns one domain. Rahul sends `/pnl` to the LAKSHMI bot to get a live P&L snapshot at any moment, even while ATO is running in the background.

---

## `params.json` Reference (LAKSHMI)

See `telegram/bots/lakshmi/params.json` for the full current file.

| Group           | What it controls                                     | Key values (defaults)                   |
| --------------- | ---------------------------------------------------- | --------------------------------------- |
| `quiet_hours`   | Scheduled P&L reports suppressed outside this window | `08:00` – `23:30` IST                   |
| `mtm`           | MTM loss alert — fires IMMEDIATELY (no quiet hours)  | threshold `−₹5,000`, interval 300s      |
| `profit_target` | Alert when cumulative MTM crosses profit target      | target `₹50,000`                        |
| `trailing`      | Trailing stop thresholds for alert notifications     | hard stop `−₹8,000`, activate `₹12,000` |
| `pnl_report`    | End-of-day P&L summary after market close            | `15:35` IST, includes positions         |
| `retry`         | Retry config for MTM / balance fetch calls           | 3 attempts, 3s delay, ×2 backoff        |
| `alert_format`  | Control verbosity of alert messages                  | show legs, hide greeks, `₹` symbol      |

---

## Commands (anticipated — not yet fully designed)

| Command | Purpose                                                            |
| ------- | ------------------------------------------------------------------ |
| `/pnl`  | Live P&L on demand — shows current MTM across all Batman positions |

---

## Files to Create (Coding Phase)

| File                           | Purpose                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `telegram/bots/lakshmi/bot.py` | LAKSHMI async entry point — MTM alerts, profit target, EOD P&L, /pnl |

---

## Design Status

- `params.json` ✓ built
- `token.env` + `token.env.example` ✓ built
- Detailed behaviour design: **PENDING** — to be designed in a future session
