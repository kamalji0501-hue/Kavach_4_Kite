# Prabhat Mukti Design (Morning Hedge Exit Spec)

Status: DESIGN_PARTIALLY_LOCKED
Last Updated: 2026-05-14
Owner Bot Domain: KAVACH -> PRABHAT MUKTI
Purpose: Define the full design for the morning hedge-sell module that exits
overnight hedges bought by RATRIPAL the previous evening.

---

## 1) Scope and Intent

RATRIPAL buys overnight hedges at ~15:20 IST and writes a handoff file.
Prabhat Mukti reads that file the next morning, confirms with the user, and
sells those hedges at the market-open time chosen by the user.

Secondary responsibility: if the market opens in a gap-breach scenario
(spot outside the short strikes), Prabhat Mukti must first buy ATO protection
on the breached side before proceeding with the hedge sell.

---

## 2) Architecture (Locked)

No new Telegram bot is introduced. The 3-bot rule (DRISHTI / KAVACH / LAKSHMI)
stays intact.

| Component     | File                                                 | Role                                    |
| ------------- | ---------------------------------------------------- | --------------------------------------- |
| Logic module  | `modules/prabhat_mukti.py`                           | All decision and execution logic        |
| Bot prompts   | `kavach-2.0/bat_telegram/bots/kavach2/bot.py`                    | All user-facing confirm/deny/time-pick  |
| Handoff input | `data/analytics/hedge_box/prabhat_mukti_handoff.csv` | Written by RATRIPAL, read+updated by PM |
| P&L output    | `data/analytics/prabhat_mukti/pm_trade_log.csv`      | Written by PM after sell execution      |
| Config        | `config/settings.json` — `prabhat_mukti` block       | All tunables, no hardcoding             |
| Events        | `core/event_bus.py` — 2 new events                   | Sell prompt request + execution done    |

Reason: KAVACH already owns all trading HITL (Hedge Box confirm/deny, emergency exit confirm).
Prabhat Mukti sell is a trading action; KAVACH is the natural owner of the user-facing flow.

---

## 3) RATRIPAL Handoff File — Augmentation Required

Current handoff fields written by RATRIPAL:
```
trade_date, request_id, deployment_file, side, zone, action,
symbol, strike, qty, order_id, spot, dte, break_even, status
```

Two new fields must be added to enable P&L calculation:

| New Field   | Source                                                   | Notes                                           |
| ----------- | -------------------------------------------------------- | ----------------------------------------------- |
| `buy_price` | `broker.get_order_details(order_id)` after verified fill | Actual avg fill price, not LTP at decision time |
| `buy_time`  | `utils.now_ist().isoformat()` at moment of verified fill | IST timestamp when order was confirmed TRADED   |

The existing `spot` field already captures NIFTY spot at buy time.
Status value written by RATRIPAL: `"verified_buy"`.

---

## 4) Prabhat Mukti Module Schedule (Locked)

```
Module type : always-on (same as ratripal)

09:00 IST   — Module wakes; reads handoff file for status = "verified_buy" rows
            — If no pending rows: log, sleep, try again at 09:05; stop by 09:25
            — If pending rows: publish PRABHAT_MUKTI_SELL_PROMPT → KAVACH shows prompt

09:14 IST   — Confirmation deadline: timeout behavior applied (OPEN QUESTION PM-Q1)

09:15–09:20 — Sell execution window: module places market SELL at user-selected time

09:25 IST   — Module marks itself done for the day; sleeps till next trading day
```

All times above are config-driven. No hardcoded IST times in module code.

---

## 5) Normal Flow — Step by Step (Locked)

### Step 1: Module starts at 09:00 AM
1. Load rows from handoff file where `status == "verified_buy"`.
2. If none: sleep 5 min, retry. If still none by 09:20: log no-action and stop.
3. Fetch current NIFTY spot to check for gap scenario (see Section 6).
4. If no gap: proceed to normal sell flow.
5. If gap on one or both sides: execute gap flow first (Section 6), then proceed.

### Step 2: KAVACH sends per-side confirmation prompt
KAVACH shows each eligible hedge individually with:
- Symbol, strike, qty
- Buy price (from handoff), buy time, NIFTY spot at buy
- Current LTP of the option
- Zone and DTE at time of buy (context only)

Buttons per side: `[✅ Sell CE]  [❌ Skip CE]` and `[✅ Sell PE]  [❌ Skip PE]`

### Step 3: KAVACH asks sell time
After user responds for all sides (or at least one confirmed):
```
[9:15 AM] [9:16 AM] [9:17 AM]
[9:18 AM] [9:19 AM] [9:20 AM]
[❌ Cancel all]
```
Six options, selection-only (no free text). Config key: `prabhat_mukti.sell_time_options`.

### Step 4: Module waits until selected time, then places market SELL
- Market order, SELL side
- Records sell_price (from broker order details after fill), sell_time, NIFTY spot at sell

### Step 5: KAVACH sends execution summary per side
- Symbol, qty, buy price vs sell price, P&L in points and rupees
- NIFTY spot at buy time vs at sell time

### Step 6: Module writes P&L row and updates handoff file
- P&L row → `data/analytics/prabhat_mukti/pm_trade_log.csv`
- Handoff row status → `"sold"`

---

## 6) Gap / Black Swan Scenario (Partially Locked)

### 6A) What is a gap breach (Locked)

Checked at exactly 9:15 IST (market open) using live NIFTY spot.

Breach definition is identical to the ATO module:
- CE gap breach: `spot >= ce_short_strike` (even 1 point above = breach)
- PE gap breach: `spot <= pe_short_strike` (even 1 point below = breach)

This is evaluated using `ce_short` and `pe_short` from the active deployment file.

### 6B) ATO strike for gap scenario (Locked)

Same formula as normal ATO protection module:
- CE side: `ce_short_strike + ato.strike_offset` (default: `ce_short + 50`)
- PE side: `pe_short_strike - ato.strike_offset` (default: `pe_short - 50`)

Config key reused: `ato.strike_offset`. No separate config needed.

### 6C) ATO already engaged (Locked)

If state shows `ato.ce_triggered = true` at the time of gap check:
- Skip gap ATO buy for CE side; ATO is already on.
- Same for PE side: if `ato.pe_triggered = true`, skip gap ATO buy for PE.

Rationale: buying another ATO when one is already engaged would push the
position toward max loss unnecessarily.

### 6D) Gap ATO buy execution (Locked)

Auto-execute immediately. No user confirmation step for the ATO buy.
Gap is a time-sensitive scenario; user confirms the setup when registering
— no further per-event approval is needed.

After ATO buy is verified, Prabhat Mukti notifies KAVACH immediately:
```
⚠️ GAP BREACH DETECTED — CE side
  Spot at open : 25,320
  CE short     : 24,700  (breach by 620 pts)
  ATO bought   : NIFTY26MAY24750CE  @  ₹184.00  | qty 65
  Order verified ✅

Proceeding to hedge sell flow...
```

### 6E) Remaining open questions (Parked — see Section 9)

PM-G6 through PM-G12 are still unresolved. See Section 9.

---

## 7) P&L Trade Log — Fields (Locked)

File: `data/analytics/prabhat_mukti/pm_trade_log.csv`

| Field           | Description                                              |
| --------------- | -------------------------------------------------------- |
| `buy_date`      | Date RATRIPAL bought the hedge                           |
| `sell_date`     | Date Prabhat Mukti sold the hedge                        |
| `side`          | CE or PE                                                 |
| `symbol`        | Option symbol                                            |
| `strike`        | Strike price                                             |
| `qty`           | Number of units                                          |
| `lots`          | qty / lot_size (from config)                             |
| `buy_price`     | Actual fill price when buying (from RATRIPAL handoff)    |
| `buy_time`      | IST timestamp of buy                                     |
| `spot_at_buy`   | NIFTY spot at time of buy                                |
| `sell_price`    | Actual fill price when selling                           |
| `sell_time`     | IST timestamp of sell                                    |
| `spot_at_sell`  | NIFTY spot at time of sell                               |
| `pnl_pts`       | sell_price − buy_price (positive = profit on hedge)      |
| `pnl_rupees`    | pnl_pts × qty                                            |
| `spot_move_pts` | spot_at_sell − spot_at_buy (overnight NIFTY movement)    |
| `zone_at_buy`   | Zone RATRIPAL classified (Green / White / Orange / etc.) |
| `action_at_buy` | RATRIPAL action label                                    |
| `sell_decision` | `confirmed` / `auto_timeout` / `auto_mode` / `gap_flow`  |

---

## 8) Configuration Block (Proposed — `settings.json`)

```json
"prabhat_mukti": {
    "enabled": true,
    "prompt_time_ist": "09:00",
    "gap_check_time_ist": "09:15",
    "sell_window_end_ist": "09:25",
    "sell_time_options": [
        "09:15", "09:16", "09:17", "09:18", "09:19", "09:20"
    ],
    "auto_mode": false,
    "auto_sell_time": "09:15",
    "confirmation_timeout_seconds": 840,
    "gap_breach_check_enabled": true,
    "ato_on_gap_breach": true,
    "jagran_on_failure": true
}
```

All values are read-only from config. No hardcoding in module code.

---

## 9) Open Questions — Parked for Next Session

### From normal sell flow design (Session 1, 2026-05-14):

PM-Q1 — TIMEOUT BEHAVIOR
  If user does not respond to sell confirmation before 09:14 IST:
  Option A: Auto-proceed and sell at 09:15 (safest for risk management)
  Option B: Skip selling, raise JAGRAN alert for manual action
  Option C: Keep waiting until 09:25 cutoff, then alert

PM-Q2 — PARTIAL SELL
  If user confirms CE sell but skips PE sell, should only CE be sold?
  Or is it all-or-nothing?

PM-Q3 — DENIED HEDGES
  If user presses Skip on a side, that row stays in handoff file.
  Is the deny final for that morning, or should PM re-prompt after some interval?

PM-Q4 — BATMAN COMPLETE BEFORE 9 AM
  If /batman_complete was called the night before, the hedges are still
  open positions. Should Prabhat Mukti still sell them?

PM-Q5 — MULTI-DAY STALENESS
  If a holiday falls between buy day and sell day, should PM still process
  rows that are 2+ trading days old? Is there a max staleness threshold?

PM-Q6 — AUTO MODE TOGGLE COMMAND
  Through which bot/command should the user toggle auto mode at runtime?
  (KAVACH command, config-only, or future SANCHALAK command?)

PM-Q8 — P&L REPORT EXTRAS
  Should the P&L CSV also include lot_size, product_type, and deployment_file
  name per row for full cross-reference?

PM-Q9 — SELL TIME PRECISION
  When user selects 09:16, does the module place the order at exactly
  09:16:00 IST, or anywhere in the 09:16:xx window?

### From gap scenario design (Session 2, 2026-05-14):

PM-G6 — SELL HEDGE AFTER GAP ATO
  After gap ATO buy is verified, does the hedge sell still use the normal
  time-selection flow (user picks 09:15–09:20)?
  Or should the hedge be sold immediately as part of the gap response?

PM-G7 — ONE-SIDED GAP, OTHER SIDE'S HEDGE
  If market gaps CE-side only:
  - Gap flow handles CE: buy CE ATO, then sell CE hedge
  - PE hedge has no breach — does it follow normal sell flow (user picks time)?
  Or is the entire sell workflow suspended until gap is resolved?

PM-G8 — BOTH SIDES BREACHED SIMULTANEOUSLY
  What if spot opens beyond both short strikes (extreme scenario)?
  Buy both CE and PE ATO before any hedge is sold?

PM-G9 — ATO QUANTITY IN GAP SCENARIO
  Should gap ATO use the same qty as the ATO module normally uses
  (buy_qty from deployment), or a separate config value?

PM-G10 — STATE FLAG COORDINATION WITH ATO MODULE
  After Prabhat Mukti buys ATO in a gap scenario, should it set
  state flags `ato.ce_triggered` / `ato.pe_triggered` so the ATO
  module does not try to re-buy the same ATO during normal monitoring?

PM-G11 — MASSIVE GAP DISTANCE CAP
  If spot is 500+ pts beyond the short strike, ATO buy is very expensive.
  Should there be a configurable max gap distance beyond which PM raises
  a JAGRAN alert and waits for manual instruction instead of auto-buying?

PM-G12 — POST-GAP NOTIFICATION FORMAT
  Should the gap execution summary be a separate message from the normal
  sell summary, or combined into one message?

---

## 10) What is NOT Prabhat Mukti's Responsibility

1. Deciding what hedge to buy — that is RATRIPAL's job.
2. Managing the iron condor legs — that is KAVACH + ATO module.
3. Profit trailing — that is the profit_trailing module.
4. Running at any time other than the 09:00–09:25 morning window.
5. Re-evaluating whether the hedge was the right buy — it just sells what RATRIPAL bought.
