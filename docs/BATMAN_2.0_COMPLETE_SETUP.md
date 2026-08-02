# COMPLETE SETUP

**Batman 2.0**

---

## Part 1: Introduction of Strategy

🎯 **Objective:**

Generate consistent income in **range-bound markets** using a risk-defined structure and high theta decay, while improving capital efficiency through **margin hedges** and payoff-graph-based risk management.

- **Instrument :** NIFTY 50
- **Frequency :** Weekly Setup

---

🧱 **Core Structure (Batman Legs + Margin Hedge):**

In Batman 2.0, the **core position** includes the classic Batman legs **and** the margin hedge. The margin hedge is part of core — not an optional add-on.

### A. Batman Legs (4 Legs)

| Leg | Action | Strike Price | Option Type | Quantity |
| --- | --- | --- | --- | --- |
| 1 | Buy | ATM + 250 | CE | 1 lot |
| 2 | Sell | ATM + 300 | CE | **2×** buy |
| 3 | Buy | ATM − 250 | PE | 1 lot |
| 4 | Sell | ATM − 300 | PE | **2×** buy |

Example (Center = 25,000): Sell **25,300 CE** · Buy **25,250 CE** · Sell **24,700 PE** · Buy **24,750 PE**.

### B. Margin Hedge (Inside Core — New in 2.0)

Add additional hedges approximately **1,000 points** away from the center.

Example (Center = 25,000): Buy **26,000 CE** · Buy **24,000 PE**.

- **Purpose:** margin reduction, additional protection, and participation during extreme directional moves.
- After creating all positions, generate the **payoff graph** (mandatory).
- Apply the **1% rule:** maximum projected loss should remain within **1% of deployed capital** (based on selling-leg strikes).
- If projected loss is too high, adjust **only the margin hedges** (move closer) — **do NOT** modify the four Batman strikes.
- When choosing between similar hedges, prefer **protection** over cost savings.

---

🧺 **Execution via Zerodha Basket Order:**

- All core legs (Batman + margin hedge) are executed together using **Zerodha Basket Orders**.
- **Benefits:**
  - One-click multi-leg execution
  - Slippage and ratio control
  - Avoids manual entry errors
  - Supports both limit and market orders
- **Basket sequence:** CE Buy → CE Margin hedge → CE Sell → PE Buy → PE Margin hedge → PE Sell

---

🕒 **Entry & Exit Timing:**

- **Entry:** Wednesday at **11:00 AM** (or next trading day after expiry if Wednesday is a holiday)
- **Exit:** Tuesday at **3:20 PM** (or on expiry day)

---

## Part 2: Overnight Risk Management

*(Dynamic / Overnight Hedge — rules same for Batman 2.0, with lot layers below)*

🎯 **Objective:**

Protect the core position from **overnight gaps** or black swan events.

---

🛡️ **Hedge Setup:**

- Buy **1 lot CE** at the **upper breakeven** of the core position
- Buy **1 lot PE** at the **lower breakeven** of the core position

These hedges are protective and cost-effective, given they’re placed OTM.

**Dynamic zone selection** (strike adjusted by where price sits vs payoff zones):

| Zone | Price Position | Hedge Strike Selection |
| --- | --- | --- |
| White | At breakeven strike | Standard breakeven hedge |
| Green | 1 strike inside breakeven | Move hedge 1 strike in |
| Orange | 2 strikes inside | Move hedge 2 strikes in |
| Blue | 3 strikes inside | Move hedge 3 strikes in |
| Yellow | 4 strikes inside | Move hedge 4 strikes in |
| Beyond Yellow | Past this level | No hedge required |

**Override rules:**

- Amendments can be done on either side (upside or downside) independently — the other side’s hedge remains standard (breakeven).
- If the **Extra Leg (Part 3)** is already active on a side, **no overnight hedge** is required for that side — but the other side must still carry its standard breakeven hedge.

---

🧱 **Lot Layers (Batman 2.0):**

| Layer | Quantity | Behavior |
| --- | --- | --- |
| **Standing** | **30% of buying quantity** | Stay **open continuously** with the core position |
| **Daily remainder** | Remaining dynamic-hedge quantity | Buy @ **3:20 PM** · Exit **same quantity** @ **9:20 AM** next day |

---

🕒 **Execution Timing:** *(daily remainder)*

- **Entry:** Daily at **3:20 PM**
- **Exit:** Next trading day at **9:20 AM**

The **standing 30% of buying quantity** stays with core. The **remaining** quantity is held only overnight and exited first thing in the morning.

---

## Part 3: Extra Leg (Most Important Part)

*(ATO rules — same for Batman 2.0)*

📌 **Trigger-Based Additional Protection:**

When the market breaches the range set by the **core short strikes**, an **extra long position** is added on the breached side.

📍 **Strike Selection:**

- If **ATM + 300 CE** is breached → **Buy 1 lot ATM + 350 CE**
- If **ATM − 300 PE** is breached → **Buy 1 lot ATM − 250 PE**

---

⚙️ **There will be 3 phases:**

### 1. Manual

- You can manually perform the action.

### 2. Semi automated

- Conditional ATOs (Alert Trigger Orders)
- Exit orders based on defined price levels
- As soon as the core basket is executed:
  - Conditional ATOs for **both CE and PE extra legs** are placed
- Place the ATO for both-side extra legs and enable once the setup is live
- **Exit Rules:**
  - If price returns back within the short range, exit the extra leg
  - Else exit on Tuesday at **3:20 PM**, along with the core part
  - After exit, a new ATO must be set up and enabled

**Must Disable the ATOs on Tuesday or expiry, if not triggered.**

✅ This ensures **quick response** to range breakout without manual intervention.

### 3. Full automatic

- You can use our algo for ATO management.

---

## Part 4: Margin Hedge — Big Gap / ATO Engaged

*(Batman 2.0 operator rule)*

📌 **When this applies:**

- Big **gap-up** / **gap-down**, when the market moves **beyond our sell legs**, and/or
- **ATO is engaged**

📍 **Action:**

- **Sell the next strike from our margin hedge** (on the breached side).
- Keep the original margin-hedge long; this is an added sell against that wing.

**Example (CE):**

- Margin hedge long **26,000 CE** → sell **26,050 CE**

**Example (PE — same logic, mirror):**

- Margin hedge long **24,000 PE** → sell **23,950 PE**

---

## ✅ Final Summary

| Component | Purpose | Entry & Exit Timing | Execution Method |
| --- | --- | --- | --- |
| Core Position (Batman + Margin Hedge) | Income with range-bound bias + margin efficiency | Wednesday 11:00 AM → Tuesday 3:20 PM | Zerodha Basket Order |
| Overnight Hedge — Standing 30% quantity | Continuous gap buffer with core | With core (continuous) | Zerodha basket order with core position |
| Overnight Hedge — Daily remainder | Protection from overnight gap moves | Daily 3:20 PM → Next Day 9:20 AM | Manual |
| Extra Leg (ATO) | Adjust to breakout movements | Trigger-based → Exit with core or on re-entry | Manual / semi automated / full automatic |
| Margin Hedge Gap Sell | Extreme gap / ATO response | When beyond sell legs / ATO engaged | Manual / rule-based |

---

## 📚 Information

📌 **Platform Requirements:**

- **Broker:** Zerodha
- **Charting Platforms:**
  - ✅ **TradingView** – for technical analysis, alerts & price action
  - ✅ **Sensibull** – for option chain, strategy builder, greeks & payoff analysis
- **Execution Tools:** Zerodha Kite (Web/App), Basket Orders, Conditional ATO Orders

---

💰 **Capital, Risk & Return Profile:**

- **Capital Required:** Rs. 3,50,000 per lot (approx. full setup margin including hedge legs)
- **Maximum Loss:** Limited to **~1.5% of deployed capital** per setup
- **Target Profit:** **~3% Minimum (Average of 1 year)** depending on range, IV, and breakout frequency
- **Maximum Drawdown:** **~5% of deployed capital**

---

⚠️ **Risk Notes:**

- The strategy is range-bound and may underperform in highly trending or volatile conditions.
- Protection mechanisms (standing + daily hedges + extra legs + margin hedge gap sell) are in place to manage sharp moves.
- High value of India VIX is preferred for higher returns and vice versa.
- Do **not** remove margin hedges to increase profitability.
- Do **not** modify the four Batman core strikes after deployment.
- Do **not** deploy without payoff-graph analysis.

---

🧠 **Key Concepts Used:**

- Multi-leg non-directional spread
- Theta decay as primary edge
- Margin hedge **inside** core position (~1,000 pts; 1% payoff rule)
- Breakeven-based overnight hedging with **standing 30% of buying quantity** + **daily remainder** (3:20 PM → 9:20 AM)
- Dynamic zone-based overnight strike selection
- Breakout reactivity with extra legs (ATO) — Manual / Semi automated / Full automatic
- Gap / ATO response: sell next strike from margin hedge (e.g. 26,000 → **26,050**)
- Rule-based execution + automation
- Backtest / forward-test validation as per KDFinSchool Batman program

---

*Educational strategy reference only. Options trading involves substantial risk of loss of capital. Past performance does not guarantee future results.*
