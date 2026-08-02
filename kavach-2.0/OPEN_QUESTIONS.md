# Batman v3 — Open Questions & Running Recommendations

> **Living document** — updated every session.
> Revisit before each major milestone (first live trade, first week, first month).
> Items move to ✅ RESOLVED when addressed.

---

## HOW TO USE THIS FILE

- **OPEN** = unresolved, needs a decision or implementation
- **WATCH** = technically OK for now, but worth monitoring long-term
- **RESOLVED** = decision made / implemented (keep for audit trail)

---

## 🔴 OPEN — Must resolve before first live trade

### OQ-01 · Broker API not smoke-tested with real token
**Question:** Does every broker method (`get_nifty_ltp`, `get_balance`,
`close_all_positions`, `place_order`) actually work against a live Dhan account?
**Risk:** ATO fires → `close_all_positions()` throws an unexpected exception →
positions NOT closed. No fallback.
**Action needed:**
1. Send real Dhan JWT to DRISHTI bot
2. Run `/funds` → confirm balance returns
3. Run `/legs` after manually placing 1 test option → confirm position appears
4. Test `close_all_positions` in a safe paper context before using in anger
**Owner:** Rahul (requires live Dhan account + token)
**Opened:** 2026-04-06

---

### OQ-02 · No dry-run / paper-trading mode
**Question:** How do we safely test the full Wednesday → Tuesday cycle without
putting real capital at risk?
**Risk:** First live run discovers bugs mid-trade with real money.
**Suggestion:** Add `dry_run: true` flag in `config/settings.json`.
When `dry_run=True`, broker methods log the call and return a mock result
instead of hitting Dhan API. The entire algo cycle runs — ATO triggers, orders
logged — but no real orders are placed.
**Impact:** ~30 lines of change in `core/broker.py`. High value, low effort.
**Opened:** 2026-04-06

---

### OQ-03 · Emergency exit uses market orders — no slippage guard
**Question:** When ATO fires and we need to close all positions urgently, market
orders on NIFTY options during high-volatility events can slip 10–30 pts per leg.
4 legs × 30 pts × lot_size = significant unexpected loss.
**Risk:** The very moment ATO triggers (high IV spike), liquidity is thin and
market-order slippage is worst-case.
**Options to evaluate:**
- Limit orders at LTP + N pts buffer (e.g. 5 pts inside spread)
- IOC limit with fallback to market after 2s
- Log slippage post-trade for calibration
**Decision needed:** Accept market-order risk OR implement IOC-limit fallback?
**Opened:** 2026-04-06

---

### OQ-04 · No live P&L visibility during trade (LAKSHMI deferred)
**Question:** LAKSHMI (MTM, /pnl, EOD summary) is deactivated. During an active
deployment, there's no in-app way to see current P&L without opening Dhan manually.
**Risk:** ATO retrace might have improved the position significantly but without
MTM visibility, Rahul may over-manage or under-manage.
**Action needed:** Enable LAKSHMI before first live trade, or at minimum
before leaving a position overnight.
- Uncomment LAKSHMI in `main.py` (5 lines)
- Uncomment LAKSHMI sidebar in `simulator/index.html`
**Effort:** ~15 min (code is already written and tested)
**Opened:** 2026-04-06

---

### OQ-05 · Condor structure not validated in /register wizard
**Question:** The 5-step wizard accepts any strikes the user selects, including
structurally invalid condors (e.g. CE sell < CE buy, or strikes on wrong side
of spot).
**Risk:** A mis-tap during /register deploys an invalid condor. Batman arms
ATO on wrong strikes. No warning is given.
**Suggested validation (during wizard Step 5 / confirm):**
```
PE BUY strike  < PE SELL strike < spot < CE SELL strike < CE BUY strike
```
If violated → show error + restart wizard from Step 1.
**Effort:** ~20 lines in `telegram/bots/kavach/bot.py` `wizard_confirm()`.
**Opened:** 2026-04-06

---

### OQ-06 · ATO cycle counter may not survive restart correctly
**Question:** If the process crashes mid-ATO (e.g. protection bought,
VPS reboots before retrace), the `ato.ce_cycles` counter in the deployment file
may not reflect cycles already executed.
**Risk:** Batman thinks it has 2 cycles left, but in reality 0 are available
(max_cycles already consumed). Could allow over-hedging.
**Suggestion:** On process restart, re-count cycles from broker positions:
"how many protection legs are currently OPEN?" → that is `cycles_used`.
**Requires:** Broker position API returning open option contracts.
**Opened:** 2026-04-06

---

## 🟡 WATCH — OK now, revisit after first live month

### OQ-07 · Lot sizing: batman_lots vs actual NIFTY lot size
**Watch:** `batman_lots` N means CE/PE SELL = 2N lots, CE/PE BUY = N lots.
NIFTY lot size is 75 (post-2024 revision). Tradehull API may expect qty in
number of lots OR number of shares. Confirm which unit before first trade.
**Opened:** 2026-04-06

---

### OQ-08 · Token expiry window is hardcoded at 20h
**Watch:** `broker.needs_reauth()` warns after 20h. Dhan JWT lifetime is 24h.
If Rahul sends the token at 9AM, warning fires at 5AM next morning — before
market open, no one sees it.
**Suggestion:** Make the warn-at-N-hours value configurable in `settings.json`.
Also consider a proactive DRISHTI reminder at a fixed time (e.g. 8:30 AM)
rather than a rolling 20h clock.
**Opened:** 2026-04-06

---

### OQ-09 · Profit trailing logic not stress-tested on real 0DTE data
**Watch:** `profit_trailing.py` starts on Tuesday (0DTE). The trailing stop
parameters (`target_pct`, `trail_pct`) are from `settings.json` defaults.
These have not been back-tested or forward-tested on real 0DTE NIFTY data.
**Question:** Are the default values (whatever they are) appropriate for
NIFTY 0DTE, which can move 500+ pts in final 2 hours?
**Action:** Run 3-4 paper trades watching trailing log output. Calibrate.
**Opened:** 2026-04-06

---

### OQ-10 · Overnight hedge skipped on 0DTE — correct? Edge case on Monday
**Watch:** `overnight_hedge.py` skips when today is 0DTE (Tuesday). But what
if Monday is a market holiday? Then Tuesday becomes 1DTE, and there IS overnight
risk. Does the module handle this correctly?
**Suggestion:** Verify the DTE calculation in `overnight_hedge.py` uses a
proper trading-calendar check, not just `weekday() == Tuesday`.
**Opened:** 2026-04-06

---

### OQ-11 · No alerting if a module silently dies
**Watch:** If `ato_protection.py` daemon thread crashes (uncaught exception in
its loop), it dies silently. The heartbeat log will say "module offline" but
Rahul won't see that unless he checks logs.
**Suggestion:** When heartbeat detects a stopped module that should be running,
send a KAVACH push notification automatically.
**Effort:** ~10 lines in `batman_main()` heartbeat loop.
**Opened:** 2026-04-06

---

### OQ-12 · VPS uptime / restart automation not specified
**Watch:** The plan is `python main.py` on VPS. If VPS reboots, Batman stays
offline until someone SSH-es in. In a live trade, this could be catastrophic.
**Suggestion:** Add a `systemd` service file or `supervisor` config so Batman
auto-restarts on reboot. The process-restart recovery logic already handles
the state reload — the infra piece is missing.
**Opened:** 2026-04-06

---

### OQ-13 · SANCHALAK authorized run failure containment policy (resolved)
**Decision:** During current testing phase, containment is alert-only.
Failure must be immediately dual-published to source chat and JAGRAN,
while the run is not auto-stopped by SANCHALAK.
**Owner:** Rahul (design decision)
**Opened:** 2026-05-03
**Resolved:** 2026-05-17

---

## ✅ RESOLVED

| ID     | Question                                      | Resolution                                                                                      | Date       |
| ------ | --------------------------------------------- | ----------------------------------------------------------------------------------------------- | ---------- |
| OQ-R01 | ATO fires too early (at retrace offset)?      | Fixed: fires at sell strike exactly. Retrace pts = exit-only buffer.                            | 2026-04-04 |
| OQ-R02 | Thread-safety: asyncio.create_task in threads | Fixed: `run_coroutine_threadsafe(coro, loop)` + `_fire()` helper in KAVACH + LAKSHMI            | 2026-04-06 |
| OQ-R03 | `/exit` blocks other commands while running   | Fixed: `concurrent_updates=True` on KAVACH builder + `asyncio.to_thread()` for broker calls     | 2026-04-06 |
| OQ-R04 | ARTHA references remaining anywhere           | Fixed: full rename to LAKSHMI, zero ARTHA refs.                                                 | 2026-04-06 |
| OQ-R05 | SANCHALAK failure containment policy          | Locked: alert-only during testing; dual-publish to source chat + JAGRAN; no SANCHALAK auto-stop | 2026-05-17 |

---

## 🔵 PARKED — Prabhat Mukti Design (out of active scope as of 2026-05-17)

These questions are from the 2026-05-14 design sessions. All must be answered
before `modules/prabhat_mukti.py` coding starts.
Do not ask or work this section unless the user explicitly reactivates PRABHAT MUKTI scope.
Reference: `telegram/design/prabhat_mukti_design.md`

### Normal Sell Flow — PM-Q1 through PM-Q9

**PM-Q1 — Timeout behavior**
If user does not respond to the sell confirmation before 09:14 IST:
- Option A: Auto-proceed and sell at 09:15 (safest for risk management)
- Option B: Skip selling for today, raise JAGRAN alert
- Option C: Keep waiting until 09:25 cutoff, then alert
**Opened:** 2026-05-14

**PM-Q2 — Partial sell**
If user confirms CE sell but presses Skip on PE sell (or vice versa):
- Sell only the confirmed side?
- Or is it all-or-nothing?
**Opened:** 2026-05-14

**PM-Q3 — Denied hedges**
If user presses Skip on a side, that row stays in handoff file.
Is the skip final for that morning, or should PM re-prompt after some interval?
**Opened:** 2026-05-14

**PM-Q4 — Batman complete before 9 AM**
If `/batman_complete` was called the night before (e.g. expiry Tuesday),
the overnight hedges are still open positions.
Should Prabhat Mukti still sell them regardless of batman_complete state?
**Opened:** 2026-05-14

**PM-Q5 — Multi-day staleness**
If a holiday falls between buy day and sell day (e.g. RATRIPAL bought Thursday,
but Friday was a holiday, so PM runs Monday):
- Should PM still process rows that are 2+ trading days old?
- Is there a max staleness threshold (e.g. only sell if buy_date within last 3 trading days)?
**Opened:** 2026-05-14

**PM-Q6 — Auto mode toggle command**
Through which bot/command should the user toggle auto mode at runtime?
- A new `/prabhat_mode` command in KAVACH?
- Config-only (restart needed)?
- Future SANCHALAK command?
**Opened:** 2026-05-14

**PM-Q8 — P&L report extras**
Should the P&L CSV include `lot_size`, `product_type`, and `deployment_file`
name on each row for full cross-reference capability?
**Opened:** 2026-05-14

**PM-Q9 — Sell time precision**
When user selects 09:16, should the module place the order at exactly
09:16:00 IST, or anywhere in the 09:16:xx window?
**Opened:** 2026-05-14

---

### Gap / Black Swan Scenario — PM-G6 through PM-G12

**PM-G6 — Sell hedge after gap ATO buy**
After gap ATO buy is verified, does the hedge sell still use the normal
time-selection flow (user picks 09:15–09:20)?
Or should the hedge be sold immediately as part of the gap response?
**Opened:** 2026-05-14

**PM-G7 — One-sided gap, other side's hedge**
If market gaps CE-side only (CE breached, PE not):
- Gap flow handles CE: buy CE ATO, then sell CE hedge
- PE hedge has no breach — does it follow normal sell flow (user picks time)?
- Or is the entire workflow suspended until gap resolution?
**Opened:** 2026-05-14

**PM-G8 — Both sides breached simultaneously**
What if spot opens beyond both short strikes (extreme scenario)?
Should both CE and PE ATO be bought before any hedge is sold?
**Opened:** 2026-05-14

**PM-G9 — ATO quantity in gap scenario**
Should gap ATO use the same qty as the normal ATO module uses
(buy_qty from deployment), or a separate config value?
**Opened:** 2026-05-14

**PM-G10 — State flag coordination with ATO module**
After Prabhat Mukti buys ATO in a gap scenario, should it set state flags
`ato.ce_triggered` / `ato.pe_triggered` so the normal ATO module does not
try to re-buy the same ATO during its monitoring loop?
**Opened:** 2026-05-14

**PM-G11 — Massive gap distance cap**
If spot is 500+ pts beyond the short strike, gap ATO buy will be very expensive.
Should there be a configurable max gap distance beyond which PM raises a JAGRAN
alert and waits for manual instruction instead of auto-buying?
**Opened:** 2026-05-14

**PM-G12 — Post-gap notification format**
Should the gap execution summary be a separate message from the normal sell
summary, or combined into one message?
**Opened:** 2026-05-14

---

## 📋 IMPROVEMENT IDEAS (not urgent, future consideration)

| ID    | Idea                                                                                | Effort |
| ----- | ----------------------------------------------------------------------------------- | ------ |
| ID-01 | Add `/pnl` shortcut to KAVACH as a passthrough to LAKSHMI (shows same data, 1 bot)  | Low    |
| ID-02 | Webhook mode instead of polling when on VPS (lower latency, less Telegram API load) | Medium |
| ID-03 | Back-test ATO + trailing parameters on 6 months of historical NIFTY weekly data     | High   |
| ID-04 | Add position-size auto-suggestion based on available margin (`/funds` output)       | Medium |
| ID-05 | Rate-limit guard: if >3 ATO cycles fire in one day, auto-pause and alert Rahul      | Low    |
| ID-06 | KAVACH `/history` command — show last 5 completed deployments from archive folder   | Low    |
| ID-07 | Integrate a simple keep-alive ping to a UptimeRobot / healthcheck.io URL            | Low    |

---

*Last reviewed: 2026-04-06 | Next review: Before first live trade*
