# Batman v3 — Test Scenarios
## Simulation model, scenario specs, and mock flows for each testing batch.
## Last updated: 2026-04-04

---

## Demo/Validation Tool

`telegram/design/batman_simulation.html` — open in any browser.

An **interactive step-by-step Telegram simulation** using real Apr 7, 2026 positions.
Covers all 3 bots (DRISHTI → KAVACH → LAKSHMI) with clickable inline keyboard buttons.
Use it to:
- Show stakeholders exactly what the bot UX looks like before code is written
- Walk through the wizard flow to catch UX gaps
- Validate the step order against the design doc

---

## Canonical Position Dataset — Apr 7, 2026

All scenarios in Batches 2–6 use this same real position set unless otherwise noted.
Source: Dhan broker app screenshot, 04-Apr-2026, 14:45 IST.

```
Underlying : NIFTY
Expiry     : 07-Apr-2026 (Tuesday, 3 DTE from trade date)
NIFTY Spot : ₹22,713.10
```

| Role          | Symbol            | Direction | Qty  | Avg ₹ | LTP ₹ | Day P&L         |
| ------------- | ----------------- | --------- | ---- | ----- | ----- | --------------- |
| PE BUY        | NIFTY07APR22050PE | LONG      | 780  | 95.19 | 79.05 | −₹12,587.25     |
| PE SELL       | NIFTY07APR22000PE | SHORT     | 1560 | 87.00 | 72.00 | +₹23,400.00     |
| CE SELL       | NIFTY07APR23200CE | SHORT     | 1560 | 76.00 | 71.10 | +₹7,644.00      |
| CE BUY        | NIFTY07APR23150CE | LONG      | 780  | 88.09 | 83.50 | −₹3,578.25      |
| **Total P&L** |                   |           |      |       |       | **+₹14,878.50** |

ATO strikes (auto-calculated, ato_step=50):
```
PE ATO: NIFTY07APR21950PE  →  fires when NIFTY ≤ 21,950  (22000 − 50)
CE ATO: NIFTY07APR23250CE  →  fires when NIFTY ≥ 23,250  (23200 + 50)
Margin: 763 pts (PE side) / 537 pts (CE side)
```

---

## BATCH 2 Scenarios — KAVACH Deploy Wizard

### Scenario KAV-01: Happy Path — Full 4-step wizard ✅

Pre-state: No existing deployment file.

```
Input:  /deploy
Step 1: User taps NIFTY07APR22050PE  (PE BUY  — LONG  780)
Step 2: User taps NIFTY07APR22000PE  (PE SELL — SHORT 1560)
Step 3: User taps NIFTY07APR23200CE  (CE SELL — SHORT 1560)
Step 4: User taps NIFTY07APR23150CE  (CE BUY  — LONG  780)
Step 5: Summary shown with ATO auto-calc
Step 6: User taps "✅ Confirm & Arm Batman"

Expected:
  - data/deployments/batman_2026-04-04_HH-MM.json written
  - File matches schema in testing/mocks/deployment_apr7.json
  - deploy_log.jsonl has: wizard_started, positions_selected, confirmed
  - KAVACH reply: "✅ Batman armed. KAVACH is watching."
  - CE ATO: NIFTY07APR23250CE  |  PE ATO: NIFTY07APR21950PE
```

### Scenario KAV-02: Cancel at Step 2 ✅

Pre-state: No existing deployment file.

```
Input:  /deploy
Step 1: User taps NIFTY07APR22050PE  (PE BUY)
Step 2: User taps "❌ Cancel"

Expected:
  - Zero files written in data/deployments/
  - deploy_log.jsonl has: wizard_started, wizard_cancelled
  - KAVACH reply: "❌ Deployment cancelled. No file written. Run /deploy again when ready."
```

### Scenario KAV-03: File already exists — safety check flow ✅

Pre-state: `data/deployments/batman_2026-03-29_09-15.json` exists.

```
Input:  /deploy
Expected:
  Bot sends:  "⚠️ Batman is currently ARMED. Running /deploy will pause ATO monitoring..."
              [Yes, continue]  [❌ Cancel]

  → If Cancel: wizard aborts. Existing file untouched.
  → If Yes:    existing file moved to archive/, wizard proceeds to Step 1.
```

### Scenario KAV-04: Wizard timeout ✅

Pre-state: No deployment file.

```
Input:  /deploy
Step 1: User taps PE BUY
Trigger: 120 seconds pass with no input at Step 2

Expected:
  - Zero files written
  - deploy_log.jsonl has: wizard_started, wizard_timeout
  - KAVACH reply: "⏳ Wizard timed out. No file written. Run /deploy again."
```

### Scenario KAV-05: /batman_complete flow ✅

Pre-state: `batman_2026-04-04_10-23.json` exists. Algo running.

```
Input:  /batman_complete
KAVACH sends confirmation:
  "Are you sure? This will stop monitoring and archive the deployment file."
  [✅ Yes]  [❌ Cancel]

If ✅ Yes:
  - Algo modules stopped (ATO, trailing)
  - batman_2026-04-04_10-23.json moved to data/deployments/archive/
  - deploy_log.jsonl appended: batman_complete
  - state reset (confirmed=False, batman_done=True)
  - KAVACH reply: "✅ Batman complete. Algo reset. Deploy fresh on Wednesday."
```

### Scenario KAV-06: /exit emergency ✅

Pre-state: 4 positions open. Deployment file exists.

```
Input:  /exit
KAVACH sends confirmation (30s timeout):
  "🚨 Emergency Exit? CLOSE ALL POSITIONS immediately. CANNOT be undone."
  [✅ Yes — Close all now]  [❌ Cancel]

If ✅ Yes:
  - All 4 positions closed at market (4 orders placed)
  - Deployment file archived
  - State cleared
  - KAVACH reply: "🚨 Emergency Exit executed. All positions closed."

If timeout (30s no response):
  - Nothing changes
  - KAVACH reply: "Emergency exit timed out. Positions unchanged."
```

---

## BATCH 3 Scenarios — DRISHTI Token & Health

### Scenario DRI-01: Token delivery happy path ✅

```
VPS starts with no token.
DRISHTI sends: "🔴 Broker not connected. Paste your Dhan access token."
User sends JWT string.

Expected:
  - broker.hot_reload_token(client_code, token) called
  - TokenStore.save(token) called → data/access_token.json written
  - DRISHTI validates: NIFTY LTP fetched successfully
  - DRISHTI replies: "✅ Broker connected! NIFTY LTP: ₹22,713. Token expires: tomorrow 08:35 IST."
```

### Scenario DRI-02: Token validation fails ✅

```
User sends a bad/expired JWT.

Expected:
  - broker.hot_reload_token() called (token accepted into memory)
  - NIFTY LTP fetch raises BrokerError (bad credentials)
  - DRISHTI replies: "⚠️ Token received but validation failed — check token."
  - TokenStore.save() NOT called (bad token not persisted)
```

### Scenario DRI-03: VPS restart with persisted token ✅

```
Pre-state: data/access_token.json exists, saved 3 hours ago (valid, < 20h).

Expected:
  - main.py startup: TokenStore.load() finds token
  - broker.connect_with_token(client_code, token) called
  - DRISHTI sends: "⚡ Batman ONLINE. Token auto-loaded (age: 3.0h). Expires in 21h."
  - No user action needed.
```

### Scenario DRI-04: Scheduled reminder at 09:00 ✅

```
Pre-state: Token last saved > 24h ago (expired).
Current time: 09:00 IST on a trading day (weekday, not NSE holiday).

Expected:
  - Reminder fires: "⚠️ Market opens at 9:15. Access token is expired! Paste new token."
  - Message sent with disable_notification=False (normal alert — market hours)
```

### Scenario DRI-05: Silent post-market message ✅

```
Pre-state: Token expired.
Current time: 23:00 IST.

Expected:
  - Reminder fires
  - Message sent with disable_notification=True (silent — outside market hours)
  - Phone does not ring; message appears silently in chat
```

### Scenario DRI-06: Reminder suppressed when token is valid ✅

```
Pre-state: Token saved 2 hours ago (fresh, < 24h).
Scheduled reminders: 09:00, 15:30, 23:00.

Expected:
  - None of the scheduled reminders fire
  - No message sent at all
```

---

## BATCH 4 Scenarios — LAKSHMI MTM & P&L

### Scenario LAK-01: MTM update (periodic) ✅

```
Every 15min during market hours, LAKSHMI fetches LTPs and sends:

📊 Batman MTM Update — 04-Apr-2026 · 14:45 IST
NIFTY Spot: ₹22,713.10  |  DTE: 3

Leg             LTP     Avg     P&L
───────────────────────────────────
PE BUY  22050   79.05   95.19  -12,587 🔴
PE SELL 22000   72.00   87.00  +23,400 🟢
CE SELL 23200   71.10   76.00   +7,644 🟢
CE BUY  23150   83.50   88.09   -3,578 🔴
───────────────────────────────────
💰 Total P&L : +₹14,878.50  🟢
Range: 21,950 ↔ 23,250 (763 / 537 pts)
```

### Scenario LAK-02: Hard stop alert ✅

```
MTM drops below hard_stop_loss (e.g. −₹30,000).

Expected:
  - Immediate LAKSHMI alert (no quiet hours check — safety critical)
  - "🔴 HARD STOP HIT. MTM: −₹32,400. Run /exit immediately."
```

### Scenario LAK-03: ATO trigger notification ✅

```
CE ATO fires (triggered by KAV).

Expected:
  - LAKSHMI sends: "🚨 CE ATO TRIGGERED. NIFTY: ₹23,258. Bought NIFTY07APR23250CE x1560."
  - Sent with disable_notification=False regardless of time (trade event)
```

### Scenario LAK-04: /pnl command ✅

```
User sends /pnl to LAKSHMI.

Expected:
  - LAKSHMI fetches live LTPs from broker
  - Returns same formatted MTM table
  - Quick response (< 3s)
```

---

## BATCH 5 Scenarios — Integration

### Scenario INT-01: ATO reads deployment file ✅

```
Pre-state: batman_2026-04-04_10-23.json exists in data/deployments/.

ATOProtection tick:
  - Reads file (not state.json)
  - Extracts: ce_sell_strike=23200, pe_sell_strike=22000
  - Sets: ce_protect_symbol=NIFTY07APR23250CE, pe_protect_symbol=NIFTY07APR21950PE
  - Begins monitoring with retrace_points from settings.json
```

### Scenario INT-02: Deploy wizard arms ATO ✅

```
Step 1: KAVACH wizard completes → batman_2026-04-04_10-23.json written
Step 2: ATO module next tick → detects file → reads strikes → begins watching

Verify:
  - Both steps happen without restart
  - ATO strikes match what wizard calculated
```

### Scenario INT-03: Batman complete — full cleanup ✅

```
/batman_complete received:
  1. KAVACH archives deployment file
  2. ATO module next tick: no file in data/deployments/ → enters WAIT state
  3. state.deployment.confirmed = False
  4. AlgoScheduler stops ticking  
  5. LAKSHMI goes silent (no MTM updates — no deployment)

All verified in a single test run.
```

### Scenario INT-04: VPS restart full reconnect ✅

```
1. System running.
2. main.py killed (simulate VPS restart).
3. main.py restarted.

Expected:
  - TokenStore.load() → token found (< 24h) → broker connected automatically
  - data/deployments/batman_*.json found → ATO reads it → begins monitoring
  - DRISHTI sends startup notification: "⚡ Batman ONLINE. Reconnected from saved state."
  - No user action required — fully automatic recovery
```

---

## BATCH 6 Scenario — End-to-End Full Flow

### Scenario E2E-01: Wednesday entry to Tuesday expiry ✅

```
Day 0 (Wednesday): Deploy positions. Run /deploy wizard. ATO armed.
Day 1 (Thursday):  AlgoScheduler auto-starts algo at 09:15.
                   NIFTY moves — ATO monitoring ticks every 60s.
                   No breach. Quiet day.
Day 2 (Friday):    NIFTY spikes near CE side. ATO fires. Retrace. ATO exits.
                   LAKSHMI sends ATO triggered + retrace exit notifications.
Day 3 (Monday):    Profit trailing activates (profit > threshold).
                   Trailing stop moves up with NIFTY movement.
Day 4 (Tuesday):   Expiry day. AlgoScheduler sends EOD prompt.
                   Positions expire worthless. Rahul runs /batman_complete.
                   Deployment archived. Algo reset. Ready for next week.

Final P&L confirmed via LAKSHMI EOD summary.
```

The interactive simulation in `batman_simulation.html` covers a compressed version of this flow with real Apr 7 data.
