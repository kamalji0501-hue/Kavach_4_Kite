# DRISHTI (दृष्टि) — Detailed Design
## Bot 1 | Infrastructure Health + Dhan Access Token Management + AlgoScheduler Prompts
## Design Doc | Locked: 2026-03-20 | Updated: 2026-04-04 | Status: DESIGN COMPLETE — Coding next

---

## Role

DRISHTI is the **infrastructure health, access token, and daily algo prompt bot**. It has three purposes:
1. Remind Rahul to update the Dhan access token (which expires every 24 hours)
2. Monitor broker connectivity health during market hours and alert immediately on failure
3. Send the AlgoScheduler's daily Telegram prompts (start-time picker, EOD reminder)

It runs silently when everything is healthy. It only speaks when something needs attention.

> **Process model (LOCKED 2026-04-04):** DRISHTI runs as an asyncio task inside a single `python main.py` process on the VPS, alongside KAVACH, LAKSHMI, and all algo modules. Rahul interacts with it from mobile — the VPS runs 24×7.

---

## Core Responsibilities

| #   | Responsibility                                                                                                | When active                             |
| --- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 1   | **Connection validation** — validate token by fetching NIFTY LTP + GIFT Nifty after every token update        | On every token receipt                  |
| 2   | **Market hours monitor** — check connection health every hour during trading                                  | 09:15–15:30 IST, NSE trading days       |
| 3   | **Interactive token reminder** — scheduled prompt with Yes/No buttons when token is expired                   | 09:00, 15:30, 23:00 IST (weekdays only) |
| 4   | **Token collection** — accept token string from user at any time via Telegram                                 | 24/7                                    |
| 5   | **On-demand commands** — `/health` (full report), `/ping` (alive check)                                       | 24/7                                    |
| 6   | **AlgoScheduler daily start-time prompt** — "What time should the algo start today?" (time picker)            | ~09:00 IST on active deployment days    |
| 7   | **AlgoScheduler EOD reminder** — "Batman complete for today?" prompt after market close                       | ~15:35 IST when deployment armed        |
| 8   | **Fleet health dashboard** — report status of bots/modules with active/deactive timestamps and today schedule | On-demand via DRISHTI status query      |

---

## Two Alert Types

### TYPE 1 — Scheduled Token Reminder
- Fires on **NSE weekdays only** (Mon–Fri, not public holidays)
- **Suppressed** if token was updated within the last 24 hours (still valid)
- **Fires** if token is expired or was never set
- Reminder times in `params.json → token_reminders.times_ist` (defaults: `["09:00", "15:30", "23:00"]`)
- **Quiet hours apply** — no outbound messages before 08:00 or after 23:30 IST

### TYPE 2 — Immediate Health Alert
- Fires **any time, immediately** — no quiet hours, no suppression, even if token is valid
- Triggers:
  - Broker API call fails (connection error, auth error)
  - NIFTY LTP fetch fails → alert with specific error reason
  - GIFT Nifty LTP fetch fails → alert with specific error reason
  - Any module crashes unexpectedly
- Alert format: `"❌ [Health Alert] Cannot fetch NIFTY LTP. Error: {reason}. Check connection."`
- If the incident is in DRISHTI's JAGRAN allowlist, the same incident is dual-published to DRISHTI chat and JAGRAN.

#### DRISHTI initial JAGRAN seed scenarios (LOCKED — 2026-05-03)

- LTP/validation fetch failure after all retries are exhausted
- broker disconnected / broker connection failure
- token expired or stale token event
- token validation/update failure requiring user attention

Timestamp format default for incident display:
- `HH:MM IST, DD Mon YYYY`

Error display default:
- Show extracted raw broker/API error text rather than shortened summaries.

Incident display addition:
- Show incident ID when available.

### Combined Alert Logic

| State                       | Action                                                          |
| --------------------------- | --------------------------------------------------------------- |
| Token valid + health OK     | Silence — no messages                                           |
| Token valid + health FAIL   | TYPE 2 fires immediately                                        |
| Token expired + health OK   | TYPE 1 fires at next configured reminder window                 |
| Token expired + health FAIL | TYPE 2 fires immediately + TYPE 1 fires at next reminder window |

---

## Reminder Times & Logic

Default times (configurable in `params.json → token_reminders.times_ist`):

| Time (IST) | Context                                                                      |
| ---------- | ---------------------------------------------------------------------------- |
| **09:00**  | Pre-market — market opens at 09:15. Token must be ready before that.         |
| **15:30**  | Post-market — day trading just ended. Update token for the next trading day. |
| **23:00**  | Night check — token expiring soon. Renew before tomorrow morning.            |

**Suppression rules — reminder does NOT fire if:**
- Today is a weekend (Sat/Sun) or NSE public holiday
- Token was updated within the last 24 hours (still valid)
- Current time is outside quiet hours (before 08:00 or after 23:30 IST)

---

## Interactive Reminder Flow

When a reminder fires and token is expired:

```
DRISHTI → User:   ⚠️ Dhan access token not updated.
                  Do you want to update it now?
                  [✅ Yes, Update Now]  [❌ No, Remind Later]

If ✅ Yes:
  DRISHTI → User:  Please send your Dhan access token now.
  User → DRISHTI:  <token string>
                   → Triggers Token Validation Sequence (below)

If ❌ No  or  30s timeout (no response):
  Log: user declined
  Wait silently until next reminder slot
  At next slot → repeat exact same prompt with Yes/No buttons again
```

This cycle repeats at every configured reminder interval until the user updates the token.

---

## Token Validation Sequence

Triggered when any token string is received (whether from the interactive Yes-flow above, or sent directly by user at any time):

```
1. Store token string + record IST timestamp
2. Hot-reload broker config           (no bot restart required)
3. Determine which LTP source is available:
     Market open   (09:15 – 15:30 IST)  →  Fetch NIFTY LTP via Dhan broker API
     GIFT window   (06:00 – 23:45 IST)  →  Fetch GIFT Nifty LTP  (Dhan → yfinance fallback)
     Both windows closed                 →  Skip LTP validation entirely
4. On fetch failure → retry:  3 attempts, 5s delay, ×2 backoff
5. All retries fail:
     ❌  "Token received but validation failed. Error: {reason}. Please check and resend."
6. Fetch success:
     ✅  "Token updated & validated. NIFTY: {ltp} | GIFT Nifty: {gift_ltp}. Expires {time} IST."
7. Reset reminder scheduler — next reminder recalculated from new token expiry time
```

---

## Market Hours Connection Monitor

Runs as a background coroutine, active only during NSE trading hours on NSE trading days:

```
During 09:15 – 15:30 IST on NSE trading days:
  Every {check_interval_seconds} (default: 3600s / 1 hour):
    → Fetch NIFTY LTP
    → Success?   Log: healthy, continue.
    → Failure?   Retry (3 attempts, 5s delay, ×2 backoff)
    → All retries failed?
         → ❌ IMMEDIATE ALERT (TYPE 2 — no quiet hours, no suppression, fires instantly):
            "❌ [Health Alert] NIFTY LTP fetch failed. Error: {reason}. Check connection."
```

---

## GIFT Nifty

- Full name: NSE IFSC NIFTY 50 Futures (traded on NSE IFSC / GIFT City exchange)
- Wide trading window: approx 06:00–23:45 IST (much wider than NSE 09:15–15:30)
- Purpose: when NSE is closed (after 15:30), GIFT Nifty is the only live NIFTY price indicator
- Acts as a leading indicator for next-day NIFTY gap up/down
- Symbol candidates to try in Dhan: `"GIFT NIFTY"`, `"NIFTYBEES"` — needs live testing to confirm
- Fallback if Dhan doesn't support: `yfinance`, `NSEpy`, or Upstox market feed
- Config: `params.json → gift_nifty.symbols` (list to try in order) + `gift_nifty.fallback_source`

---

## Telegram Commands (24/7, always active)

| Command             | Response                                                                                |
| ------------------- | --------------------------------------------------------------------------------------- |
| `/health`           | Token status (valid/expired + time remaining) + NIFTY LTP + GIFT Nifty LTP + bot uptime |
| `/ping`             | `🟢 DRISHTI alive. {timestamp} IST`                                                      |
| `/fleet_status`     | Interactive status menu + tabular health report for selected bot/module                 |
| Direct token string | Triggers Token Validation Sequence immediately — no need to wait for a reminder         |

---

## Fleet Health Dashboard (LOCKED — 2026-05-02)

### Objective

DRISHTI must provide a single command to inspect operational health of other bots/modules.
This is read-only visibility for fast decision-making.

### Scope

Supported targets (initial design):
- DRISHTI
- KAVACH
- LAKSHMI
- RATRIPAL
- PRABHAT MUKTI

### Interaction model

Telegram does not support native dropdown UI, so DRISHTI uses inline option buttons.

Flow:
1. User sends `/fleet_status`.
2. DRISHTI replies with target options (inline keyboard).
3. User taps one target (example: RATRIPAL).
4. DRISHTI returns tabular status summary immediately.

### Required response fields (tabular)

| Field                      | Meaning                                                                                   |
| -------------------------- | ----------------------------------------------------------------------------------------- |
| Target                     | Selected bot/module name                                                                  |
| Current State              | ACTIVE or INACTIVE. Active target means currently enabled/running in the present session. |
| Active Since               | IST timestamp when target entered ACTIVE                                                  |
| Last Deactivated At        | IST timestamp when target most recently became INACTIVE                                   |
| Last Heartbeat             | Last known heartbeat timestamp                                                            |
| Upcoming Schedules (Today) | Remaining scheduled actions/checkpoints still pending for the current IST day             |
| Last Error                 | Latest known error summary (if any)                                                       |
| Last Incident ID           | Most recent incident identifier, if available                                             |

### Canonical message format

DRISHTI should render a compact monospaced table. Example shape:

```
Target                 State     Active Since         Last Deactivated      Last Heartbeat
RATRIPAL               ACTIVE    2026-05-02 09:20    2026-05-01 15:35      2026-05-02 11:00

Upcoming Schedules (Today):
- 15:35 EOD checkpoint
- 23:00 token reminder window

Last Error:
- None

Last Incident ID:
- None
```

### Data source contract

DRISHTI reads status from shared runtime state and scheduler metadata:
- lifecycle state keys per target
- last activation/deactivation timestamps
- heartbeat timestamps
- today's scheduled tasks from scheduler configuration

### Non-goals

- This feature does not start/stop modules.
- This feature does not modify schedules.
- This feature does not auto-route incidents by itself.

---

## Three Async Coroutines

DRISHTI's bot.py runs three parallel async coroutines:

| Coroutine            | Responsibility                                                             |
| -------------------- | -------------------------------------------------------------------------- |
| `reminder_scheduler` | Fires token reminders at configured times. Checks suppression rules first. |
| `market_monitor`     | Health check loop during 09:15–15:30. Fires TYPE 2 alert on LTP fail.      |
| `telegram_listener`  | Handles incoming messages (token strings) and `/health`, `/ping` commands. |

All three run independently. Market_monitor self-gates on market hours. Reminder_scheduler self-gates on weekday + quiet hours + token validity.

---

## Access Token — Background

- Dhan API JWT access token generated manually from Dhan developer portal (`web.dhan.co → Profile → Access DhanHQ APIs`)
- Valid for exactly **24 hours** from generation time — must be regenerated daily
- Status shown in Dhan portal as: `"Time to Expiry: 1 day | Status: Active | Revoke"`
- `pin_totp` auto-refresh mode was **abandoned** (unstable) — code uses `Tradehull(mode="access_token", ...)`
- DRISHTI hot-updates the token in `core/broker.py` + writes to `token.env`/config — no restart needed

---

## `params.json` Reference (DRISHTI)

| Group             | What it controls                                          | Key values (defaults)                         |
| ----------------- | --------------------------------------------------------- | --------------------------------------------- |
| `quiet_hours`     | Outbound reminder messages suppressed outside this window | `08:00` – `23:30` IST. Bot accepts 24/7.      |
| `token_reminders` | Scheduled reminders when Dhan access token is expired     | `09:00`, `15:30`, `23:00` IST (weekdays only) |
| `health_check`    | Proactive health reports during trading window            | `08:45`–`15:45`, every `3600s`                |
| `retry`           | Retry config for broker/LTP API calls                     | 3 attempts, 5s delay, ×2 backoff              |
| `gift_nifty`      | GIFT Nifty symbol candidates + fallback source            | `["GIFT NIFTY", "NIFTYBEES"]`, yfinance       |
| `alerts`          | Immediate health alerts (no quiet hours, always fire)     | broker/LTP/module failures, 60min expiry warn |

---

## Files to Create (Coding Phase)

| File                           | Purpose                                                                       |
| ------------------------------ | ----------------------------------------------------------------------------- |
| `telegram/bots/drishti/bot.py` | Bot entry point — 3 async coroutines, /health, /ping handlers, token listener |

→ **Full flow diagram:** [telegram/design/drishti_flow.html](drishti_flow.html) — open in browser
