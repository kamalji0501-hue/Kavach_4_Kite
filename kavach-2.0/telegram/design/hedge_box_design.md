# Hedge Box Design (RATRIPAL Input Spec)

Status: CODED_PENDING_VALIDATION
Last Updated: 2026-07-25
Owner Bot Domain: KAVACH 2.0 -> RATRIPAL -> ADITYA
Purpose: Preserve the full Hedge Box context and examples in one place so implementation can proceed without losing continuity.

## Working Principle (Locked Direction)

1. **KAVACH 2.0** arms the Batman deployment (core sell/buy legs) and owns Hedge Box HITL confirm/deny.
2. **Standard break-even is fixed:** CE = `ce_sell_strike + 200`, PE = `pe_sell_strike − 200` (config: `hedge_box.standard_break_even_offset_points`, default 200), then rounded to the 50-pt strike grid.
3. RATRIPAL derives this fixed BE from sell legs — it does **not** use Register-confirmed `risk.break_even.*` for strike math.
4. Color-box (Green/Orange/Blue/Yellow) inside depths are measured from that fixed BE; White zone buys at the fixed BE strike.
5. Hedge Box decisions are made at a daily checkpoint (default 15:15 IST) and then carried overnight.
6. All tunables are configuration-driven under `hedge_box`.
7. Runtime v1 is in `modules/ratripal.py` with KAVACH 2.0 confirmation callbacks and broker-verified handoff to **ADITYA**.


## User-Confirmed Locks (2026-05-10)

The following points are now locked from user answers:
1. White zone is the region between the two Green boxes (inside Hedge Box, not outside).
2. One-strike-inside always means 50 points from break-even.
3. If ATO is already engaged on breached side and spot is outside short strike at 15:15, do not add Hedge Box hedge on that breached side.
4. In that ATO override case, carry standard hedge on the opposite side.
5. Hedge quantity source is half of sell legs, which equals buy-side deployed quantity.
6. Hedge Box does not apply holiday-driven DTE shifting; each trading day uses its own day box set.
7. CE-side and PE-side evaluation are independent.
8. 0DTE has no Hedge Box action.
9. Daily run time is 15:15 IST and must remain config-driven.
10. Hedge strike selected by box-depth logic must never collide with sold strike mechanics.
11. DTE is working-days only (Indian market calendar; Saturday and Sunday are excluded).
12. If a sell leg is missing for one side, Hedge Box skips that side only; opposite side remains independently evaluable.
13. If a side has no sell strike, Hedge Box skips that side; ATO/KAVACH 2.0 handles breach protection.

## 1) Scope and Intent

Hedge Box is a decision framework that uses fixed sell-leg break-even levels (200 pts outside) to decide what hedge should be carried into overnight risk windows.

This document is intentionally separate from generic design docs because:
1. Hedge Box logic is stateful and day-sensitive (4DTE to 0DTE).
2. Sell/buy legs come from the KAVACH 2.0 deployment; BE is derived as sell ± 200.
3. Runtime is `modules/ratripal.py`; overnight exit handoff goes to ADITYA.

## 2) Upstream Source of Truth

**KAVACH 2.0** provides the armed deployment (sell/buy strikes and qty). RATRIPAL computes fixed standard break-even from sell strikes:

1. CE fixed BE = `positions.ce_sell.strike + hedge_box.standard_break_even_offset_points` (default 200)
2. PE fixed BE = `positions.pe_sell.strike − hedge_box.standard_break_even_offset_points` (default 200)
3. Round to 50-pt grid (`nearest_50_tie_down` via `_round_to_strike`)

Legacy deployment fields `risk.break_even.*` may still exist from older Register flows but are **ignored** by RATRIPAL strike selection.

ADITYA morning-exit reads the handoff CSV written by RATRIPAL:
`data/analytics/hedge_box/aditya_handoff.csv`


## 3) Core Hedge Box Rules Captured So Far

1. Hedge Box is break-even anchored.
2. Box width is fixed at 75 points.
3. Evaluation checkpoint is 15:15 IST (3:15 PM).
4. 0DTE has no carry-forward Hedge Box action because expiry-day carry has no utility.
5. Opposite side standard hedge must remain present.
6. If an extra leg is already active on one side, no duplicate extra hedge buy is needed for that side.
7. All thresholds and times must be config-driven (no hardcoding).

## 4) DTE Layer Activation

The number of active color boxes grows as expiry approaches.

1. 4DTE: Green only.
2. 3DTE: Green and Orange.
3. 2DTE: Green, Orange, and Blue.
4. 1DTE: Green, Orange, Blue, and Yellow.
5. 0DTE: No box logic.

Final color-order map (from short strike inward toward center):
1. 4DTE: Green
2. 3DTE: Orange, Green
3. 2DTE: Blue, Orange, Green
4. 1DTE: Yellow, Blue, Orange, Green
5. 0DTE: None

Action-depth map by color (locked):
1. Green -> 1 strike inside
2. Orange -> 2 strikes inside
3. Blue -> 3 strikes inside
4. Yellow -> 4 strikes inside

Decision precedence (locked):
1. Color-zone selection by DTE map
2. Safety guardrail clamp near sold strike
3. ATO engaged override behavior
4. Opposite-side standard hedge

Break-even to strike rounding (locked):
1. Strikes are 50-point spaced.
2. Within each 100-point bucket:
3. [xx00, xx25) rounds to xx00.
4. [xx25, xx75) rounds to xx50.
5. [xx75, xx100) rounds to next xx00.

Interpretation note:
The model always has four conceptual box types per side, but day-level activation determines which ones are live for that day.

## 4A) Breach Definition (Aligned with ATO Protection)

**CRITICAL**: Hedge Box uses the **exact same breach definition as ATO Protection**.

Breach occurs when NIFTY spot crosses into the short strike territory:

1. **CE-side breach**: `spot >= ce_short_strike`
   - Example: CE short at 24,750 → breach when spot reaches 24,750.01 or higher
   - Represents UPSIDE penetration into sold CE leg risk

2. **PE-side breach**: `spot <= pe_short_strike`
   - Example: PE short at 24,150 → breach when spot drops to 24,149.99 or lower
   - Represents DOWNSIDE penetration into sold PE leg risk

**"Outside" (synonymous with "breached")**: Market has violated the sold strike boundary.
**"Inside"** (synonymous with "not breached"): Market is still within safe territory (below CE short, above PE short).

---

## 5) Zone Semantics (Current Capture)

Current captured behavior from discussion:
1. White zone: carry standard break-even hedge behavior on both sides.
2. Green zone on a side: carry one strike inside from break-even on that side, and standard hedge on opposite side.
3. Breach case on day-1: if market already crossed short strike and ATO hedge is engaged, carry engaged hedge on breached side and standard hedge on opposite side.
4. Breach case without ATO engaged: if market is already outside short strike at checkpoint and ATO is not engaged, Hedge Box must buy breach protection on that side.
5. Orange, Blue, and Yellow use the same per-side inside-strike logic pattern as Green, with only depth changing by color.

Locked boundaries (v2):
1. CE breach boundary: spot >= ce_short.
2. PE breach boundary: spot <= pe_short.
3. Bands are layered from short strike inward using box_width chunks.
4. White band is any spot that is not in an active side band and not breached.

3DTE mapping validated from Core Position scenario:
1. CE Orange band (closest to CE short): [ce_short - box_width, ce_short].
2. CE Green band (next inside): [ce_short - 2*box_width, ce_short - box_width].
3. PE Orange band (closest to PE short): [pe_short, pe_short + box_width].
4. PE Green band (next inside): [pe_short + box_width, pe_short + 2*box_width].

Boundary precedence (v2):
1. Breach check is applied first.
2. Active side bands are evaluated next (closest-to-short band first).
3. White is fallback when neither breach nor active band match.

Boundary inclusions (locked):
1. CE Orange includes the lower edge and excludes the upper edge, except breach has priority at CE short.
2. PE Orange excludes the lower edge and includes the upper edge, except breach has priority at PE short.
3. Example CE: 24675 is Orange, 24750 is Breach.
4. Example PE: 24225 is Orange, 24150 is Breach.

## 5A) Locked Formula Frame

This frame is now locked for runtime implementation:
1. strike_step_points = 50.
2. box_width_points = 75.
3. checkpoint_time_ist = 15:15.
4. White mode means standard break-even hedge on both sides.
5. Green side mode means one strike inside on that side and standard on opposite side.
6. If breached side has already engaged ATO hedge and override is enabled, carry engaged hedge on breached side.
7. If breached side is outside short strike and ATO is not engaged, buy breach protection on that side.
8. Standard hedge strike on a side equals fixed standard break-even strike of that side (sell ± 200).
9. One-strike-inside mapping:
	CE side inside strike = ce_break_even - strike_step.
	PE side inside strike = pe_break_even + strike_step.
10. Orange, Blue, and Yellow use the same formula shape with steps 2, 3, and 4 respectively.
11. Hedge quantity = deployed buy-side quantity for that side (equivalent to half sell-side quantity).

## 5B) Short-Strike Guardrail (Critical Constraint)

This constraint comes from position-construction safety and must be applied after box-depth strike computation.

Core idea:
1. Box depth determines a target strike from break-even (inside 1/2/3/4 strikes).
2. That target must be clamped so Hedge Box never recommends a strike that effectively breaks sold-leg hedge mechanics.

Current captured rule from user explanation:
1. CE side (upside breach context): nearest safe hedge cannot go below sold CE hedge band; practical cap/floor reference is sold_ce + 50.
2. PE side (downside breach context): nearest safe hedge cannot go beyond sold PE hedge band; practical cap/floor reference is sold_pe - 50.
3. If computed inside target violates this guardrail, choose the nearest valid strike at the guardrail boundary.

Why this exists:
1. If break-even is too close, deep inside-box mapping (especially Blue/Yellow) may push recommended strike into invalid or undesired region around sold strikes.
2. In such cases, guardrail takes precedence over raw inside-depth mapping.

## 6) Sample Scenario (From Discussion)

This section captures your spoken reference sample so logic can be tested deterministically.

Sample setup (as discussed):
1. Center: 24450.
2. Short side legs: CE short 24750, PE short 24150.
3. Long side legs: CE buy 24700, PE buy 24300.
4. Checkpoint time: 15:15 IST.
5. Box width: 75 points.

Reference image artifacts:
1. Prod Data/Hedge Box/22 Apr 26 - 28 Apr 26/Core Position.png
2. Prod Data/Hedge Box/22 Apr 26 - 28 Apr 26/Hedge Box 24450 Centre.png

Sample outcomes captured:
1. If spot is in White zone at checkpoint, carry break-even hedge on both CE and PE sides.
2. If spot is in CE-side Green zone at checkpoint, carry CE one-strike-inside hedge and PE standard hedge.
3. If spot is in PE-side Green zone at checkpoint, carry PE one-strike-inside hedge and CE standard hedge.
4. If day-1 spot is outside Green and beyond short strike, and ATO is already engaged on breached side, carry that engaged strike on breached side and standard hedge on opposite side.

Additional example captured:
1. If PE break-even is close (example around 24000) and Yellow-box mapping asks 4 strikes inside, computed target can overshoot sold-PE safety band.
2. In that case, Hedge Box should clamp to sold_pe - 50 boundary strike instead of following deeper inside mapping.

## 7) Configuration Contract (No Hardcoding)

Proposed config section to add under settings:
1. hedge_box.enabled
2. hedge_box.check_time_ist
3. hedge_box.box_width_points
4. hedge_box.strike_step_points
5. hedge_box.active_by_dte.4dte
6. hedge_box.active_by_dte.3dte
7. hedge_box.active_by_dte.2dte
8. hedge_box.active_by_dte.1dte
9. hedge_box.active_by_dte.0dte
10. hedge_box.use_ato_engaged_override
11. hedge_box.default_opposite_side_mode
12. hedge_box.rounding_mode_reference
13. hedge_box.white_zone_policy
14. hedge_box.quantity_mode
15. hedge_box.dte_source
16. hedge_box.single_checkpoint_only
17. hedge_box.use_deployment_calendar

## 7A) Proposed Default Config Values

1. enabled = true once runtime module is wired; current repo default is enabled with state gating.
2. check_time_ist = 15:15.
3. box_width_points = 75.
4. strike_step_points = 50.
5. active_by_dte = {4: [green], 3: [green, orange], 2: [green, orange, blue], 1: [green, orange, blue, yellow], 0: []}.
6. use_ato_engaged_override = true.
7. default_opposite_side_mode = standard_break_even.
8. white_zone_policy = dual_standard_break_even.
9. quantity_mode = deployed_buy_qty_per_side.
10. dte_source = trading_day_static (no holiday compression for Hedge Box box-set selection).
11. single_checkpoint_only = true.
12. ato_override_requires_outside_short = true.

## 7B) Human-In-The-Loop Execution Locks

1. If only one side is eligible for Hedge Box action, the confirmation prompt must show only that side.
2. Confirm, deny, and timeout behavior stays identical whether one side or both sides are shown.
3. If broker execution or post-order verification fails for a Hedge Box buy, raise JAGRAN immediately and do not retry automatically.
4. Only successfully executed and broker-verified buys are persisted to the ADITYA handoff CSV.

## 8) Remaining Clarifications / Future Options

Only unresolved points are listed below:
1. Whether to allow optional second checkpoint when single_checkpoint_only=false.

## 9) Runtime Status (2026-05-14)

Implemented now:
1. `modules/ratripal.py` computes Hedge Box side plans, waits for KAVACH confirm/deny for up to 2 minutes, auto-proceeds on timeout, and buys verified hedge orders.
2. `kavach-2.0/bat_telegram/bots/kavach2/bot.py` now sends Hedge Box prompts and records confirm/deny responses through inline buttons.
3. `main.py` wires RATRIPAL into the active runtime.
4. Verified buys are written to `data/analytics/hedge_box/aditya_handoff.csv`.
5. Broker execution/verification failures raise KAVACH/JAGRAN incidents without retry.

Still pending:
1. Optional second-checkpoint support remains undecided and is not implemented.
2. ADITYA exit module is still not coded; only the handoff CSV contract is implemented.
3. Simulator/manual validation of confirm, deny, timeout, and failure paths is still required.

## 8A) Final Question Set (Unresolved Only)

Please answer these in order. One-line answers are enough.

1. Orange/Blue/Yellow side actions: should these be +2/+3/+4 inside strikes from break-even, or another mapping?
2. Please confirm exact guardrail formulas:
	CE side allowed hedge strike should be max(computed_ce_strike, sold_ce + 50), correct?
	PE side allowed hedge strike should be min(computed_pe_strike, sold_pe + 50), correct?
3. Outside-short without ATO active: should we force immediate standard hedge, inside hedge, or no action?
4. If break-even is skipped by user, should Hedge Box be fully disabled for that deployment?
5. Do you want to keep one checkpoint only forever, or allow optional second checkpoint in future config?

## 8B) Negative and Edge Scenarios to Validate

1. Wide gap open at 15:15 directly outside short strike while ATO not yet active.
2. Spot oscillates around Green boundary near 15:15; no duplicate hedge should be produced.
3. Holiday-adjacent trading day still uses its own configured day box-set (no compression shift).
4. CE and PE sides both near White boundaries due to rapid move and mean reversion.
5. Existing manual extra hedge already present on side before Hedge Box run.
6. Missing deployment file or missing break-even should hard-stop recommendation.
7. break_even.skipped=true should not trigger accidental hedge selection.
8. 0DTE run should emit explicit no-action outcome.

## 9) Implementation Guidance for RATRIPAL (Design-Only)

1. RATRIPAL should run as recommendation engine first.
2. Execution should be gated by control-plane authorization.
3. Every recommendation record should include:
side, zone, spot, break-even used, selected strike, DTE, timestamp, reason code.
4. Must be idempotent per side per day per checkpoint window.

## 9A) Pre-Coding Feature Lock (2026-05-10)

The following execution features are design-locked and must be implemented together when coding starts:

1. RATRIPAL buy verification at broker:
	- After placing Hedge Box buy orders, verify corresponding broker positions are actually present.
	- Only verified buys are considered successful Hedge Box carries.

2. RATRIPAL -> ADITYA handoff artifact:
	- RATRIPAL must create a dedicated handoff file for next-day exit workflow.
	- File purpose: tell ADITYA which overnight hedges were bought and must be exited next session.
	- Scope: include only successfully verified bought hedges.

3. Telegram confirmation after successful buys:
	- Send user confirmation in Telegram chat only after broker verification passes.
	- Confirmation must identify the hedges bought for overnight protection.

4. Failure behavior:
	- If order is placed but broker verification fails, do not write it into ADITYA handoff as successful carry.
	- Emit alert/exception message flow (final wording to be locked during implementation).

5. Implementation timing lock:
	- Do NOT implement runtime code yet.
	- User will provide two additional RATRIPAL features first; coding begins after those are locked.

6. Human-in-the-loop pre-trade confirmation (new lock):
	- At 15:15 IST RATRIPAL computes planned CE/PE hedges from Hedge Box logic.
	- Bot sends Telegram pre-trade prompt announcing planned hedges and intended buy time (default 15:20 IST).
	- Prompt must explicitly list CE planned hedge and PE planned hedge for only the sides that are eligible in that cycle.
	- Prompt interaction is button-only (no text command parsing for confirm/deny path).
	- Confirmation timeout is 2 minutes (config-driven target).
	- If user does not reply within timeout, auto-buy proceeds at execution time.
	- If user explicitly denies/cancels, RATRIPAL must not place Hedge Box buys for that cycle.
	- If user explicitly confirms, RATRIPAL proceeds with buy flow and verification.
	- If one side has missing/skipped break-even, do not ask user for that side in prompt; skip that side automatically.
	- If both sides are ineligible (for example both BE missing/skipped or 0DTE), do not send buy confirmation prompt for that cycle.
	- This is an additional safety layer; final audit messages must record user response path: confirmed / timed_out_auto / denied.

7. ADITYA handoff file format and write timing:
	- Handoff artifact format is CSV (user-facing and easy to inspect).
	- Update/write handoff rows only after successful execution + broker verification.
	- Handoff rows represent overnight hedges to be exited by ADITYA next morning.

8. Deny behavior policy (HITL):
	- If user taps deny/cancel in the 15:15 cycle, skip Hedge Box buys for that cycle/day.
	- No further buy confirmation prompts should be issued for that day after explicit deny.

9. Verification and retry policy:
	- Use market orders for execution flow.
	- No automatic retry loop for execution/verification failures.
	- On broker error (margin/order rejection/other execution failure), emit immediate incident alert to JAGRAN.
	- Recovery is explicit/manual (user-driven), not auto-retry.

10. Prompt payload contract (what user sees before confirm):
	- Side-wise strike value(s).
	- LTP (last traded price) at decision/prompt time.
	- Quantity.
	- Zone.
	- DTE.
	- Break-even reference used for that side.

## 10) Validation Plan (Design to Test)

1. Unit tests for zone classification by DTE and side.
2. Golden test vectors from this document's sample scenario.
3. Replay tests using saved deployment JSON plus synthetic spot snapshots.
4. Simulator trace export for daily decision at 15:15 IST.

---

Change log:
1. 2026-05-10: Created dedicated Hedge Box design document with upstream fixed sell-leg break-even dependency, DTE layering, sample scenario capture, config-first contract, and lock-pending questions.
2. 2026-05-10: Added working principle, interim formula frame, default config values, and final-lock question set.
3. 2026-05-10: Locked user-confirmed rules for White boundaries, inside-strike, ATO override, quantity source, side independence, and 0DTE no-action.
4. 2026-05-10: Corrected DTE behavior lock: no holiday-driven DTE shifting for Hedge Box; Thursday keeps Thursday box set even if Friday is holiday.
4. 2026-05-10: Added critical short-strike guardrail section and unresolved formula lock questions based on deep-box edge case explanation.
5. 2026-05-10: Added pre-coding execution lock for broker-verified Hedge Box buys, RATRIPAL->ADITYA handoff file, and Telegram success confirmation flow.
