# Batman v3 — DESIGN DOCUMENT

> **Purpose:** Single source of truth for all NEW design decisions going forward.
> **CONTEXT.md** = what is already built and how it works.
> **DESIGN.md** = what we are designing next, phase by phase.
> **Last Updated:** 2026-05-03

---

## CORE PRINCIPLES (LOCKED)

| Principle        | Detail                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Focus**        | ATO automation is the only critical automation. Everything else is secondary.                                                    |
| **Style**        | Design first, code second. Phase by phase. No rushing.                                                                           |
| **Deployment**   | Fully flexible — user deploys positions any time, any expiry, any range. No hardcoded Wednesday/Tuesday restriction.             |
| **Out of scope** | `batman_entry` module, `overnight_hedge` module — both manual on Dhan app, always.                                               |
| **Auth**         | `pin_totp` auto-refresh abandoned (unstable). Moving to manual **access_token** mode. Token provided by user daily via Telegram. |

---

## PHASE OVERVIEW

```
Phase 0 → Drishti Bot     Infrastructure, health checks, access token management   ← CURRENT DESIGN
Phase 1 → Kavach Bot      ATO production validation, live testing                  (code exists, needs live test)
Phase 2 → Kavach Enhanced Flexible deployment (expiry, strikes, lots via Telegram)  (design pending)
Phase 3 → Lakshmi Bot     MTM alerts, profit targets, EOD P&L                      (design pending)
Parking  → Auto-entry, Auto-hedge, Multi-user                                       (do NOT pursue)
```

## NEW DESIGN CONCEPT (2026-05-03) — SANCHALAK (GLOBAL CONTROL BOT)

> Status: DESIGN_LOCKED_NOT_CODED
> Canonical bot name locked: SANCHALAK.

### Why this concept exists

Rahul wants a higher-level supervisory bot that can:
1. Turn specific downstream bots/modules on or off.
2. Support automation testing by enabling repeatable chained execution.
3. Allow unattended execution when Rahul is not available at critical times (example: 09:15–09:20 windows).
4. Apply predefined standard rules when selected automation flags are enabled.

### Working responsibility

This "global bot" is a bot-of-bots supervisor, not a trading-strategy bot.

Its likely responsibility envelope:
1. Manage enable/disable flags for downstream bots/modules.
2. Show current automation posture for the day/session.
3. Allow Rahul to pre-authorize specific automated flows.
4. Trigger standard-rule execution when enabled bots are allowed to operate unattended.

### Initial targeted downstream components

- KAVACH
- RATRIPAL
- PRABHAT MUKTI
- JAGRAN

### Key design principle

The global bot should control permissions and execution gates, but should not replace existing ownership boundaries.

That means:
1. DRISHTI still owns token/health infrastructure.
2. KAVACH still owns trading command domain.
3. JAGRAN still owns critical incident attention channel.
4. AlgoScheduler still owns schedule timing logic unless explicitly redesigned.

### Initial use cases

1. Testing mode:
  Enable selected bots/modules in sequence for repeated simulation and automation validation.
2. Unattended morning mode:
  Rahul enables approved flows in advance, and the global bot permits RATRIPAL/PRABHAT MUKTI to act under standard rules if Rahul is unavailable.
3. Safety mode:
  Rahul can globally disable one or more downstream execution paths without editing per-bot configuration.

### Likely design shape

The cleanest architecture is probably a control-plane bot, not a fourth domain bot.

That control plane would manage:
1. feature flags
2. automation authorization flags
3. per-bot enable/disable state
4. unattended-execution permissions

### Open design questions

1. Should this be a true Telegram bot, or a control layer exposed through DRISHTI?
2. Should it control bots only, or lower-level modules too?
3. What actions are allowed automatically when Rahul is absent?
4. What is the fail-safe if a globally enabled downstream bot hits an error?
5. How does this interact with existing AlgoScheduler timing ownership?
6. Does global enablement apply for one day, one session, or persist until manually disabled?

### Decisions locked in latest clarification (2026-05-03)

1. The global control system will be a separate Telegram bot (true bot-of-bots control plane), not DRISHTI command overloading.
2. Global bot controls core bot authorization state (ON/OFF) only.
3. Global bot does not control bot-internal strategy logic or low-level module internals.
4. Unattended execution is allowed only when Global Bot explicitly authorizes the target bot(s).
5. Per-bot local enablement alone must not imply unattended automation authorization.
6. Chained execution is allowed for high-speed testing runs when globally authorized.
7. Global bot should remain always running; disablement is manual by operator action.
8. If a downstream bot fails during globally authorized run, error must be captured in JAGRAN (dual publish with source).
9. Global bot acts as an authorization plane above schedule timing flows; it gates whether approved automation may execute.

### Parked open item from latest clarification

- Downstream failure containment policy is intentionally deferred for a later design pass:
  - continue remaining globally authorized bots, or
  - disable failed bot only, or
  - disable full global run.

## NEW DESIGN CONCEPT (2026-05-03) — SARANSH (SUMMARY REPORT BOT)

> Status: DESIGN_LOCKED_NOT_CODED
> Scope lock: Summary schema v1 is locked; additional sections can be appended later.
> Canonical bot name locked: SARANSH.

### Objective

Provide a post-market structured summary that consolidates execution, ATO behavior, and P&L visibility in one message.

### Trigger model

1. Automatic EOD summary after market hours.
2. Optional on-demand manual trigger.

### Minimum summary payload (v1 locked)

1. Total orders executed today.
2. Total ATO-related orders executed today.
3. Entry and re-entry points lost today (execution impact view).
4. Current running P&L with:
  - normalized one-lot equivalent
  - total deployed lots
  - total P&L amount
  - P&L percentage
5. Token status addendum:
  - token expiry state
  - reminder/update windows
  - action note (update now or skip to next slot)

### Report format and options

1. Report should support predefined sections (toggle-able/configurable over time).
2. Initial default layout should remain compact and Telegram-friendly.
3. Additional fields may be added later without breaking v1 core metrics.

### Associated summary report variants (seed)

1. EOD Core Summary:
  - order counts, ATO counts, running P&L, one-lot normalization, P&L percentage.
2. Execution Quality Summary:
  - entry/re-entry points lost and execution-impact focused metrics.
3. Ops Addendum:
  - token expiry/update reminder window context for next session readiness.

### SARANSH Data Source Contract (LOCKED — 2026-05-03)

At EOD summary time (target 15:30 IST market close window), SARANSH must ingest the ATO execution telemetry CSV generated by KAVACH and use it as the authoritative source for ATO execution-frequency and timing analysis.

Primary dependency:
1. Source file: `data/analytics/ato_execution_telemetry.csv`.
2. Producer: KAVACH/ATO execution telemetry writer.
3. Consumer: SARANSH EOD summary pipeline.

#### Ingestion timing (locked)

1. SARANSH reads telemetry snapshot during EOD summary run.
2. If telemetry file is missing or empty, SARANSH must soft-fail that section and still publish remaining summary sections with a clear note.

#### Telemetry fields SARANSH consumes (locked)

1. `timestamp_ist`
2. `deployment_file`
3. `side`
4. `action`
5. `trigger_reason`
6. `nifty_ltp_at_execution`
7. `sell_strike`
8. `trigger_level_used`
9. `protect_strike`
10. `protect_symbol`
11. `order_id`
12. `qty`
13. `poll_interval_seconds_used`

#### Derived metrics for SARANSH from telemetry (locked)

1. Total ATO orders executed today.
2. Side-wise ATO count (CE/PE) and action split (BUY entry/SELL exit).
3. Trigger-reason mix (`sell_strike_breached` vs `buffer_trigger_hit` vs `retrace_exit`).
4. Time-window density (execution clustering by timestamp buckets).
5. Strike-context recap (sell strike vs trigger level vs protect strike).

This section augments, not replaces, existing SARANSH v1 payload fields.

---

## DESIGN SPRINT (2026-04-24) — ADDITIONAL MODULES FOR RUN + END

> Scope for this session: design only, no code.
> Goal: make daily start and day/week closure deterministic before final production hardening.

### Why this sprint

Two operational steps need explicit design ownership so production behavior is predictable:
1. **Run step**: controlled start of algo tasks after readiness checks.
2. **End step**: controlled closure, archival, and reset after market day/week.

### New design entities (logical modules)

| Module (logical)               | Owner bot                        | Responsibility                                                         | Non-goals                          |
| ------------------------------ | -------------------------------- | ---------------------------------------------------------------------- | ---------------------------------- |
| **Run Readiness Orchestrator** | DRISHTI + AlgoScheduler          | Pre-start checks, start-time intent capture, start gate release        | Does not place/modify positions    |
| **Completion Orchestrator**    | KAVACH (+ LAKSHMI for reporting) | End-of-day/week confirmation, archival, cleanup checklist, state reset | Does not change ATO strategy rules |

### 1) Run Readiness Orchestrator — design

#### Trigger
- Daily 09:00 IST DRISHTI prompt (weekday/holiday aware), plus manual `/start_algo_now` override from KAVACH.

#### Inputs
- Deployment presence (`data/deployments/batman_*.json`)
- Token freshness (<24h)
- Broker heartbeat (`get_balance` or equivalent health probe)
- Market session state (open/closed)

#### Decision contract

| Condition           | Result                                 |
| ------------------- | -------------------------------------- |
| Deployment missing  | Block start + DRISHTI action message   |
| Token stale/missing | Block start + DRISHTI token reminder   |
| Broker unhealthy    | Block start + immediate health alert   |
| Market closed       | Defer start, keep selected time intent |
| All checks pass     | Release start gate to module scheduler |

#### Event contracts
- `RUN_CHECK_STARTED`
- `RUN_CHECK_FAILED` (reason enum: `NO_DEPLOYMENT`, `TOKEN_STALE`, `BROKER_DOWN`, `MARKET_CLOSED`)
- `RUN_CHECK_PASSED`
- `RUN_GATE_RELEASED`

#### Telegram UX
- DRISHTI sends compact status with pass/fail checklist.
- If blocked, message includes one next action only (no multi-action ambiguity).

### 2) Completion Orchestrator — design

#### Trigger
- Scheduled EOD prompt (DRISHTI reminder path) and explicit KAVACH `/batman_complete` confirmation flow.

#### Inputs
- Open positions snapshot
- Module running states
- Deployment metadata (created timestamp, strategy details)
- LAKSHMI daily MTM/P&L summary payload

#### Completion sequence (locked for implementation)
1. Freeze new strategy actions (pause new cycle starts).
2. Validate user intent with confirm timeout.
3. Archive active deployment JSON to `data/deployments/archive/`.
4. Stop non-essential loops in deterministic order.
5. Persist completion audit record (timestamps + operator action).
6. Reset runtime keys for next cycle readiness.
7. Publish final summary to KAVACH and LAKSHMI channels.

#### Event contracts
- `COMPLETION_REQUESTED`
- `COMPLETION_CONFIRMED`
- `COMPLETION_ARCHIVED`
- `COMPLETION_CLEANUP_DONE`
- `COMPLETION_FINALIZED`

#### Failure policy
- Archive failure is **hard-stop** (do not mark complete).
- Notification failure is **soft-fail** (retry + continue completion).
- Cleanup partial failure sets system to `SAFE_PAUSED` and raises immediate alert.

### Shared state keys (design additions)

| Key                       | Type          | Purpose                                                        |
| ------------------------- | ------------- | -------------------------------------------------------------- |
| `run.last_check_at`       | datetime      | Last readiness evaluation timestamp                            |
| `run.block_reason`        | string/null   | Current start gate block reason                                |
| `run.selected_start_time` | HH:MM/null    | User-selected start time intent                                |
| `completion.requested_at` | datetime/null | Completion request initiation                                  |
| `completion.confirmed_at` | datetime/null | Completion confirmation timestamp                              |
| `completion.archive_path` | string/null   | Archive file path for audit trace                              |
| `system.mode`             | enum          | `IDLE` \/ `READY` \/ `RUNNING` \/ `SAFE_PAUSED` \/ `COMPLETED` |

### Pending question closures from this design sprint

| Question                                 | Decision                                                        |
| ---------------------------------------- | --------------------------------------------------------------- |
| Who owns daily run prompt?               | DRISHTI owns Telegram interaction; scheduler owns timing logic  |
| Can algo start with stale token?         | No. Hard block until fresh token is validated                   |
| Can completion proceed if archive fails? | No. Completion is rejected until archival succeeds              |
| Which bot owns completion command?       | KAVACH owns `/batman_complete`; DRISHTI only reminds            |
| Where does EOD P&L belong?               | LAKSHMI publishes P&L summary, referenced by completion summary |

### Out of scope for this sprint
- Any change to ATO breach/retrace algorithm
- Any automation of manual entry/hedge modules
- Multi-user authorization redesign

### DRISHTI Fleet Status Dashboard (LOCKED — 2026-05-02)

Requirement:
- DRISHTI must provide on-demand health visibility for other bots/modules in tabular format.

Minimum output fields:
- current active/inactive state
- active-since timestamp (IST)
- last deactivated timestamp (IST)
- upcoming schedules for today (IST)
- last heartbeat and latest error summary

Interaction pattern:
- User invokes DRISHTI status query command.
- DRISHTI returns inline options for target selection (dropdown equivalent in Telegram UX).
- User selects target (example: RATRIPAL).
- DRISHTI returns immediate status table for selected target.

Scope note:
- Scenario and field-level thresholds for health severity remain design-controlled and can be extended later without changing this base contract.

### Naming Convention (LOCKED — 2026-04-24)

| Domain                         | Locked Name   | Usage                                                      |
| ------------------------------ | ------------- | ---------------------------------------------------------- |
| Overnight hedge buy near close | RATRIPAL      | Canonical name for overnight hedge entry/protection logic  |
| Morning hedge exit/unwind      | PRABHAT MUKTI | Canonical name for morning hedge release/exit phase        |
| Critical incident alert bot    | JAGRAN        | Canonical name for high-priority error and failure alerts  |
| Global control bot             | SANCHALAK     | Canonical name for bot-of-bots authorization control plane |
| Summary report bot             | SARANSH       | Canonical name for post-market execution and P&L recap bot |

#### Naming policy
- Use RATRIPAL and PRABHAT MUKTI as canonical names in all design artifacts.
- Use SANCHALAK as canonical name for the global control bot in all design and tracker artifacts.
- Use SARANSH as canonical name for the summary report bot in all design and tracker artifacts.
- User-facing messages can show full phrase: PRABHAT MUKTI.
- Internal shorthand MUKTI is allowed only as an alias, not as replacement of the canonical phrase.

### Critical Incident Routing (LOCKED — 2026-05-02)

#### Objective
- JAGRAN is a dedicated Telegram bot/channel for incidents that require immediate user attention.
- JAGRAN receives only high-priority errors (critical and major), not routine informational updates.

#### Mandatory sources to publish into JAGRAN
- DRISHTI
- KAVACH
- RATRIPAL
- PRABHAT MUKTI

#### Routing contract
- Any critical incident emitted by the mandatory sources must be published to JAGRAN.
- Any major incident with immediate trading impact risk should also be published to JAGRAN.
- Informational or normal lifecycle messages must stay in source-domain bots and must not flood JAGRAN.
- Error events must be dual-published: source-domain bot/channel and JAGRAN.
- Source-domain channel gets context continuity; JAGRAN gets immediate-attention copy.
- Not all errors are routed to JAGRAN. Only selected immediate-action incidents are routed.

#### Source-wise incident selection policy (LOCKED — 2026-05-02)

- Applies uniformly to DRISHTI, KAVACH, RATRIPAL, and PRABHAT MUKTI.
- Each source must maintain an allowlist of scenarios that qualify for JAGRAN routing.
- Scenario definitions are intentionally pending and will be finalized incrementally in future design sessions.
- Until scenario lists are finalized, treat this as a design gate and do not auto-route all source errors to JAGRAN.

#### Initial confirmed allowlist seeds (LOCKED — 2026-05-03)

DRISHTI:
- NIFTY or validation LTP fetch failure after retry exhaustion
- broker disconnected / broker connection failure
- token expired / stale token event
- token update/validation path failure that requires user attention

KAVACH:
- margin shortfall
- order rejection
- emergency exit failure
- archive/completion failure with immediate operational impact

Policy note:
- These are seed scenarios, not the final exhaustive list.
- More scenarios will be appended source-by-source in a dedicated JAGRAN error matrix.

#### Minimum alert payload for JAGRAN
- source (DRISHTI/KAVACH/RATRIPAL/PRABHAT MUKTI)
- severity (critical or major)
- category (margin/api/connectivity/system/module)
- short title (one-line human-readable reason)
- first_seen timestamp and repeat_count
- suggested next action

#### Standard error message format (LOCKED — 2026-05-02)

All high-priority errors must include this readable sentence format:

"{part} has thrown an error at {timestamp}. Error message: {error_message}"

Required fields:
- part: module or bot component name (example: DRISHTI, KAVACH, RATRIPAL, PRABHAT MUKTI)
- timestamp: event timestamp in IST
- error_message: raw or normalized exception message

Timestamp default:
- `HH:MM IST, DD Mon YYYY`

Recommended optional fields:
- incident_id
- severity
- category
- next_action

Display preference (current design default):
- Prefer extracted raw broker/API error text over shortened summaries.
- Error smart-categorization/highlighting is a later enhancement and does not replace raw error visibility in the current phase.
- Show incident ID when available.

#### Noise-control rules
- Deduplicate repeated identical alerts inside a short rolling window.
- Send state transitions only: triggered, still failing (periodic), recovered.
- Send recovery notices to JAGRAN for all incidents that were previously published there.

#### Naming lock
- Use JAGRAN as the canonical design name in all docs and user-facing references for the incident bot.

#### Logging architecture handoff
- Runtime and incident logging architecture for Phase 1 (MAIN + DRISHTI + KAVACH + JAGRAN) is locked in `telegram/design/logging_design.md` (2026-05-16).
- This includes text-log line format, IST timestamp policy with milliseconds, time-window log segmentation, correlation IDs, incident/recovery ledger policy, and EOD workbook output structure.

### KAVACH Register Flow Extension — Break-even Confirmation (LOCKED — 2026-04-25)

> Applies inside KAVACH `/register` wizard after leg selection and before final arm/deployment confirmation.

#### Objective
- KAVACH must calculate break-even levels from registered legs.
- KAVACH must show both sides and ask user confirmation.
- If user rejects a suggested break-even, user can enter manual strike.
- Manual strike is accepted only if it is a multiple of 50.
- KAVACH must provide a Skip Break-even option for users who only want ATO/KAVACH flow.

#### Break-even pipeline
1. Calculate raw lower/upper break-even from the selected position structure.
2. Ignore decimals by truncating toward zero (integer part only).
3. Round integer BE to nearest 50 with tie-down rule:
  - remainder > 25: round up to next 50
  - remainder <= 25: round down to previous 50
4. Use rounded values as suggested BEs shown to user.

#### Examples (locked)
- `24241` -> `24250`
- `25458` -> `25450`
- `24225` -> `24200` (midpoint goes down)
- `25475` -> `25450` (midpoint goes down)

### ATO Entry Buffer + Side-wise Retrace (LOCKED — 2026-05-03)

> Status: DESIGN_LOCKED_NOT_CODED
> Scope: KAVACH register-time configuration + ATO trigger/exit behavior only.

#### Why this change

Round-number strikes often act as liquidity-grab zones. To avoid immediate ATO entry exactly at a psychological strike, the user can configure a positive trigger buffer per side.

#### Naming lock

Internal schema names:
1. `ce_entry_buffer_points`
2. `pe_entry_buffer_points`
3. `ce_retrace_points`
4. `pe_retrace_points`

User-facing wording:
1. "ATO Trigger Buffer" (entry side)
2. "Retrace Points" (exit side)

#### Value constraints (locked)

1. Entry buffer values are non-negative only (no negative values allowed).
2. Entry buffer maximum allowed value is 20 points.
3. Retrace points remain non-negative.
4. Quick apply option is required: user may mirror CE values to PE (and then edit if needed).

#### Trigger and exit formulas (locked)

Let:
1. `ce_sell_strike` be CE short strike.
2. `pe_sell_strike` be PE short strike.

Then trigger thresholds are:
1. CE trigger level = `ce_sell_strike + ce_entry_buffer_points`
2. PE trigger level = `pe_sell_strike - pe_entry_buffer_points`

Exit thresholds are:
1. CE retrace exit level = `ce_sell_strike - ce_retrace_points`
2. PE retrace exit level = `pe_sell_strike + pe_retrace_points`

ATO protect strike-selection logic remains unchanged.

#### Side gating interaction (locked)

1. If ATO manage side is CE-only, PE entry/retrace values are stored but ignored during runtime checks.
2. If ATO manage side is PE-only, CE entry/retrace values are stored but ignored during runtime checks.
3. If both sides are enabled, both sets are active.

#### Startup scan consistency (locked)

Startup scan breach detection must use the same buffered trigger thresholds as live monitoring to avoid behavior drift between pre-loop adoption and in-loop checks.

#### Register wizard impact (design lock)

KAVACH must capture entry and exit controls per side:
1. CE ATO Trigger Buffer
2. PE ATO Trigger Buffer
3. CE Retrace Points
4. PE Retrace Points

Wizard summary must show all four computed thresholds before final confirmation.

#### Status and notification wording (locked)

1. If side buffer > 0 and trigger fires, use wording: "buffer trigger hit".
2. If side buffer = 0 and trigger fires, keep wording: "sell strike breached".
3. `/ato_status` must display side-wise trigger and retrace levels explicitly.

#### Backward compatibility (locked)

For existing deployment files without side-wise values:
1. `ce_entry_buffer_points = 0`
2. `pe_entry_buffer_points = 0`
3. `ce_retrace_points = retrace_points` (legacy)
4. `pe_retrace_points = retrace_points` (legacy)

This guarantees old deployments keep previous runtime behavior.

#### User interaction sequence (per side)
1. Show suggested PE-side break-even and ask: Confirm or Edit.
2. If Confirm -> lock PE BE and move to CE side.
3. If Edit -> prompt user to enter BE strike for PE side.
4. Validate user input:
  - numeric integer
  - divisible by 50
5. If invalid -> error message + re-prompt same side.
6. Repeat the same flow for CE side.
7. After both sides are confirmed, proceed to final deployment confirmation.

#### Skip Break-even flow (locked)
1. At BE prompt, user can choose Skip Break-even.
2. On skip, KAVACH shows explicit warning:
  - break-even not set for this deployment
  - RATRIPAL and PRABHAT MUKTI will remain disabled
  - core KAVACH/ATO workflow continues normally
3. User must confirm skip once (guard against accidental tap).
4. After confirmation, wizard proceeds to final deployment confirmation.

#### Validation contract for manual BE input
- Valid: any integer multiple of 50 (includes 100, 150, etc.).
- Invalid: non-numeric, decimal text, or integer not divisible by 50.
- On invalid input, KAVACH must not advance wizard state.

#### Data-quality fallback (locked defaults)
- If any registered leg has missing/zero average price, KAVACH must block auto BE suggestion.
- In this case, KAVACH enters manual-only BE capture mode for both sides.
- Wizard continues only after valid manual PE and CE break-even entries (multiple of 50 rule).

#### Persistence contract (weekly/global for active deployment)
- If BE is confirmed/manual-entered: store both break-evens in runtime state for the active week/session.
- Persist BE values in deployment payload for restart safety and audit continuity.
- If BE is skipped: persist skip state so restart behavior is deterministic.

#### State keys (design additions)
- `risk.break_even.pe`
- `risk.break_even.ce`
- `risk.break_even.confirmed` (true only when both sides are confirmed)
- `risk.break_even.source.pe` (`auto` or `manual`)
- `risk.break_even.source.ce` (`auto` or `manual`)
- `risk.break_even.skipped` (true when user explicitly skips BE)
- `modules.ratripal.enabled` (gated by BE availability)
- `modules.prabhat_mukti.enabled` (gated by BE availability)

#### Deployment payload additions (design)
- `risk.break_even.pe`
- `risk.break_even.ce`
- `risk.break_even.rounding_rule` = `nearest_50_tie_down`
- `risk.break_even.skipped`

#### Non-goal
- Break-even values do not alter ATO trigger/retrace logic.
- This extension is for user confirmation, risk visibility, and downstream alerting readiness.

#### Scope lock (current phase)
- Break-even can be confirmed/edited or explicitly skipped at register-time.
- If skipped, BE-dependent modules (RATRIPAL and PRABHAT MUKTI) stay disabled for that deployment.
- KAVACH ATO flow does not depend on BE and remains fully available.
- Live BE proximity alerting is deferred to a later LAKSHMI design phase and is not part of this implementation scope.

### ATO Execution Telemetry + Poll Cooling (LOCKED — 2026-05-03)

> Status: DESIGN_LOCKED_NOT_CODED
> Scope: capture each ATO buy/sell execution event with market context and allow user-selected LTP polling cooldown.

#### Objective

When an ATO order is executed (BUY or SELL), KAVACH/ATO must persist a structured telemetry row so historical frequency, strike behavior, and time-window analysis can be done in Excel.

#### Data capture contract (locked)

Each ATO execution event (entry or exit, CE or PE) must capture:
1. timestamp_ist (human readable IST timestamp)
2. deployment_file (active `batman_*.json` reference)
3. side (CE or PE)
4. action (BUY entry or SELL exit)
5. trigger_reason (`sell_strike_breached` or `buffer_trigger_hit` or `retrace_exit`)
6. nifty_ltp_at_execution
7. sell_strike
8. trigger_level_used
9. protect_strike
10. protect_symbol
11. order_id
12. qty
13. poll_interval_seconds_used

#### Storage format (locked)

1. Primary telemetry sink: CSV file that is Excel-compatible.
2. Suggested path: `data/analytics/ato_execution_telemetry.csv`.
3. File behavior: append-only rows, with header auto-created if file does not exist.
4. This telemetry file is analytics/audit evidence; it must not be used as runtime control state.

#### Poll cooling / throttling control (locked)

KAVACH register flow must ask one additional user question:
1. "How often should I check NIFTY LTP for ATO?"
2. Allowed options (predefined only): 1 sec, 2 sec, 3 sec, 4 sec, 5 sec, 10 sec, 15 sec.
3. User must select from Telegram buttons; manual typed numeric input is not accepted for this step.

Selected value must be persisted in deployment payload and applied by ATO monitor loop as effective poll interval for this deployment.

#### Wizard impact (design lock)

`/register` must include an additional step for LTP polling frequency selection:
1. Existing ATO/retrace settings remain.
2. New poll interval step appears before final confirmation.
3. Final summary must show selected polling interval and explain API-throttling protection intent.
4. Poll step UI must be selection-only (inline keyboard/reply keyboard), not free-text entry.

#### Runtime behavior contract

1. ATO loop must honor deployment-selected poll interval (1/2/3/4/5/10/15 sec).
2. If deployment-selected value is missing (legacy files), fall back to existing config default.
3. Telemetry row write failure must not block order flow; failure should be logged as soft-fail.

#### Backward compatibility

For old deployment files without poll interval:
1. Use existing `ato.poll_interval_seconds` config value.
2. Continue normal ATO behavior with no deployment rejection.

---

## 3-BOT ARCHITECTURE (LOCKED — 2026-03-18)

|                  | **Drishti** 👁️                         | **Kavach** 🛡️                         | **Lakshmi** 💰                         |
| ---------------- | ------------------------------------- | ------------------------------------ | ------------------------------------- |
| **Name (Hindi)** | दृष्टि — Watchful Eye                    | कवच — Shield / Armor                 | लक्ष्मी — Goddess of Wealth              |
| **Role**         | Infra health + access token           | Core positions + ATO control         | MTM alerts + P&L                      |
| **Phase**        | Phase 0 — build next                  | Phase 1 — exists, rename later       | Phase 3 — future                      |
| **Config key**   | `drishti_bot`                         | `kavach_bot`                         | `lakshmi_bot`                         |
| **Env vars**     | `DRISHTI_BOT_TOKEN` `DRISHTI_CHAT_ID` | `KAVACH_BOT_TOKEN` `KAVACH_CHAT_ID`  | `LAKSHMI_BOT_TOKEN` `LAKSHMI_CHAT_ID` |
| **Code folder**  | `bots/drishti/` (new)                 | `bots/kavach/` (from current `bot/`) | `bots/lakshmi/` (new)                 |

### Why 3 separate bots?
- Each bot gets its own Telegram notification channel — custom alerts per concern area
- Easier debugging: if Kavach has an error, Drishti + Lakshmi are unaffected
- Each bot has its own token, its own chat_id — can be different Telegram groups/channels
- Failure isolation: a crash in one bot folder is contained

---

## PROPOSED FOLDER STRUCTURE (target state — not built yet)

```
batman_v3/
├── bots/                               ← NEW top-level home for all Telegram bots
│   ├── __init__.py
│   ├── drishti/                        ← Bot 1: infra + token management
│   │   ├── __init__.py
│   │   ├── bot.py                      ← main bot entry, Application builder
│   │   ├── token_manager.py            ← receive token, validate, hot-reload, persist
│   │   ├── health_checker.py           ← NIFTY LTP, GIFT Nifty LTP, broker auth, balance
│   │   └── reminder_scheduler.py       ← scheduled reminders + quiet hours logic
│   ├── kavach/                         ← Bot 2: trading commands (renamed from bot/)
│   │   ├── __init__.py
│   │   ├── bot_manager.py
│   │   ├── algo_scheduler.py
│   │   ├── auth.py
│   │   └── handlers/
│   │       ├── ato_handler.py
│   │       ├── deploy_handler.py
│   │       ├── admin_handler.py
│   │       ├── monitor_handler.py
│   │       └── hedge_handler.py
   └── lakshmi/                          ← Bot 3: MTM + P&L alerts (future)
│       ├── __init__.py
│       ├── bot.py
│       └── mtm_reporter.py
│
├── bot/            ← EXISTING code (will be migrated to bots/kavach/ in a future phase)
├── core/           ← unchanged
├── modules/        ← unchanged
├── config/         ← settings.json will get new bot sections
├── tests/          ← tests will grow with each phase
└── ...
```

> **Migration note:** `bot/` → `bots/kavach/` is a future refactor. Current session only designs/builds Drishti. Do NOT rename `bot/` until Phase 2 or later.

---

## PHASE 0: DRISHTI BOT — DETAILED DESIGN

### What Drishti does

| Responsibility              | Detail                                                                      |
| --------------------------- | --------------------------------------------------------------------------- |
| **Receive access token**    | User sends JWT token string directly to Drishti via Telegram                |
| **Capture timestamp**       | Records exact IST time of token receipt                                     |
| **Persist token**           | Writes to `config/.env` file + hot-reloads in-memory broker instance        |
| **Validate token**          | Fetches NIFTY LTP + attempts GIFT Nifty LTP immediately after update        |
| **Confirm to user**         | Sends success/failure message with price + expiry time                      |
| **Scheduled reminders**     | Fires at configured times if token expired/missing (weekdays, non-holidays) |
| **Immediate health alerts** | Fires instantly on any connection/API failure, regardless of quiet hours    |
| **On-demand commands**      | `/health`, `/token_status`, `/ping`                                         |

---

### Drishti — Token Update Flow (step by step)

```
1.  User sends access token string to Drishti bot on Telegram (e.g. "eyJ0eXAi...")
2.  Drishti detects it is a JWT token (starts with "eyJ" or matches known format)
3.  Captures IST timestamp: token_updated_at = now()
4.  Writes DHAN_ACCESS_TOKEN=<token> to config/.env
5.  Hot-reloads broker: replaces internal Tradehull instance with new token
6.  Validation:
    a. Fetch NIFTY LTP → if OK: ✅  if fail: ❌ with reason
    b. Fetch GIFT Nifty LTP → best effort (may not be supported by Dhan)
    c. Fetch balance → confirms account accessible
7.  Send Telegram reply:
    ✅ "Token updated. NIFTY: 23,450 | Balance: ₹2,45,000 | Expires: 3:35 PM tomorrow (2026-03-19)"
    OR
    ⚠️ "Token received but validation failed. NIFTY LTP error: {error}. Check token."
8.  Reset reminder scheduler: next reminder = token_updated_at + 24h (or next reminder window after expiry)
```

---

### Drishti — Two Alert Types (LOCKED)

#### Type 1: Scheduled Token Reminder
- Fires at configured reminder times in IST
- **Only fires if:** token expired OR token was never set
- **Suppressed if:** `(now - token_updated_at) < 24 hours` (token still valid)
- **Only on:** weekdays (Mon–Fri) that are NOT in the NSE holiday calendar
- **Respects quiet hours:** no outbound messages outside `quiet_hours_start` → `quiet_hours_end`
- Example suppression: token updated at 15:35 → 15:30 reminder already past → no 23:00 reminder tonight → no 09:00 reminder next morning → next reminder fires at 15:30 the following day

| Default Reminder Time | Message                                                                     |
| --------------------- | --------------------------------------------------------------------------- |
| 09:00 IST             | `⏰ Market opens at 09:15. Access token not updated! Generate and send now.` |
| 15:30 IST             | `⏰ Market closed. Update access token for next trading day.`                |
| 23:00 IST             | `⏰ Token expiring soon. Update before tomorrow.`                            |

#### Type 2: Immediate Health Alert
- Fires **instantly**, no quiet hours, no suppression — even if token is valid
- Triggers:
  - Broker API call fails (any reason)
  - NIFTY LTP fetch fails → include specific error
  - GIFT Nifty LTP fetch fails → include specific error
  - Any trading module crashes unexpectedly
- Format: `❌ [Health Alert] Cannot fetch NIFTY LTP. Error: ConnectionTimeout. Check connection.`

#### Alert decision matrix

| Token state     | Health state | Action                                                 |
| --------------- | ------------ | ------------------------------------------------------ |
| Valid (< 24h)   | OK           | Silence — nothing sent                                 |
| Valid (< 24h)   | FAIL         | **Immediate alert** (Type 2)                           |
| Expired (> 24h) | OK           | Reminder at next scheduled window (Type 1)             |
| Expired (> 24h) | FAIL         | **Immediate alert** (Type 2) + reminder at next window |
| Never set       | any          | Reminder at next scheduled window (Type 1)             |

---

### Drishti — Quiet Hours (LOCKED)

- Configured in `settings.json` under `drishti_bot`
- Default: quiet from `23:30` to `08:00` IST (i.e. late night + early morning)
- Bot **accepts** incoming token messages 24/7 — quiet hours only block **outbound** reminder messages
- Type 2 health alerts (immediate) are **exempt** from quiet hours

---

### Drishti — GIFT Nifty Support

- GIFT Nifty = NSE IFSC NIFTY 50 Futures (GIFT City, Gujarat)
- Trading window: ~06:00 IST – 23:45 IST (opposed to NSE: 09:15–15:30)
- Purpose: live NIFTY price indicator after NSE closes — useful for gap risk assessment
- **Current status:** Unknown if Dhan/Tradehull supports it
- Symbol to test: `"GIFT NIFTY"` in `tsl.get_ltp_data(names=[...])`
- **If supported:** show price in health check + token validation response
- **If NOT supported by Dhan:** defer → note in DESIGN.md as open item → skip silently
- Alternative sources (if needed): yfinance (`^NSEI`), NSEpy, Upstox WebSocket feed

---

### Drishti — Commands

| Command          | Action                                                                  |
| ---------------- | ----------------------------------------------------------------------- |
| `<token_string>` | Detect as token → update + validate + confirm                           |
| `/health`        | Run full health check → NIFTY LTP, GIFT Nifty LTP, broker auth, balance |
| `/token_status`  | Show last token update time + expiry countdown                          |
| `/ping`          | Quick connectivity check — replies with IST timestamp                   |

---

### Drishti — Config Schema (to be added to settings.json)

```json
"drishti_bot": {
    "bot_token": "${DRISHTI_BOT_TOKEN}",
    "chat_id": "${DRISHTI_CHAT_ID}",
    "enabled": true,
    "token_expiry_hours": 24,
    "reminder_times_ist": ["09:00", "15:30", "23:00"],
    "quiet_hours_start": "23:30",
    "quiet_hours_end": "08:00",
    "validate_on_update": true,
    "validate_gift_nifty": true,
    "health_check_interval_seconds": 3600
}
```

---

### Drishti — Broker Auth Mode Change

Current code uses `pin_totp` mode (unstable — abandoning):
```python
# CURRENT (being abandoned)
tsl = Tradehull(ClientCode=..., mode="pin_totp", pin=..., totp_secret=...)
```

New code will use `access_token` mode:
```python
# NEW (manual daily token)
tsl = Tradehull(ClientCode=..., mode="access_token", access_token=<jwt_token>)
```

Changes needed in `core/broker.py`:
- `BatmanBroker.connect()` — add `access_token` mode support alongside existing `pin_totp`
- `BatmanBroker.hot_reload_token(token: str)` — new method, replaces Tradehull instance in-place
- `settings.json` — add `DHAN_ACCESS_TOKEN` env var
- `.env` — add `DHAN_ACCESS_TOKEN=<token>` (updated by Drishti on each token submission)

---

## PHASE 1: KAVACH — ATO LIVE VALIDATION (design complete, code complete)

> **Status:** 99/99 tests passing. Code is production-ready. Needs first live test.

### What needs to happen in Phase 1
1. Fill in real credentials in `config/.env`
2. Run `python main.py`
3. Send `/confirm_deploy` with real Dhan positions
4. Observe ATO Startup Scan output
5. Let ATO main loop run during market hours
6. Validate breach → ATO fire → retrace → exit cycle works correctly
7. Tune `retrace_points` if needed (currently default = 5 pts)

### ATO key parameters (from current config)
| Parameter              | Value         | Configurable via                              |
| ---------------------- | ------------- | --------------------------------------------- |
| Retrace points default | 5 pts         | `/ato` command → 5/10/35/50 options           |
| Max cycles per session | 0 (unlimited) | `ato.max_cycles_per_session` in settings.json |
| Poll interval          | 2 seconds     | `ato.poll_interval_seconds`                   |
| Startup scan           | enabled       | `ato.startup_scan_enabled`                    |

---

## PHASE 2: KAVACH — FLEXIBLE DEPLOYMENT (design pending)

> **Status:** Design not started. Parking until Phase 0 + Phase 1 are complete.

### High-level intent
- Remove hardcoded Wednesday/Tuesday from deployment flow
- User should be able to specify at `/confirm_deploy` time:
  - Which **expiry** (0 = nearest, 1 = next, 2 = month-end)
  - **Sell distance** (pts from ATM for sell legs)
  - **Hedge gap** (pts from ATM for buy legs)
  - **Lot size** for this deployment
- All configurable via Telegram inline keyboard or command parameters

### Open design questions for Phase 2
- [ ] How does user specify expiry — inline keyboard (0/1/2) or command argument?
- [ ] Should defaults always come from `settings.json` and user only overrides?
- [ ] How does ATO protect strike get recomputed if sell_distance changes mid-week?

---

## PHASE 3: LAKSHMI BOT — MTM & PROFIT ALERTS (design pending)

> **Status:** Design not started. Parking until Phase 0 + Phase 1 are complete.

### High-level intent
- Dedicated bot for financial notifications — completely separate from position management
- User gets MTM alerts, trailing notifications, profit target hits in a separate Telegram channel
- Current `position_monitor.py` and profit_trailing alerts get routed here

### Planned responsibilities
| Feature                    | Detail                                      |
| -------------------------- | ------------------------------------------- |
| MTM alert at −₹5,000       | Alert once per ₹1,000 level (anti-spam)     |
| Hard stop alert at −₹8,000 | Immediate, no quiet hours                   |
| Trailing activated         | `+₹12,000 reached — trailing started`       |
| New P&L peak               | `New high: +₹15,000 — stop now at +₹13,000` |
| Trailing stop hit          | `Trailing stop hit at +₹13,000 — exiting`   |
| EOD P&L summary            | Sent at 15:35 IST daily                     |
| `/pnl` command             | Live P&L on demand                          |

---

## PARKING LOT (never pursue)

| Item                                   | Reason                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------- |
| Automated Dhan login (`pin_totp`)      | Compliance/policy blocker — Dhan requires daily human token generation |
| `batman_entry` module automation       | Manual deploy is the design. Not changing.                             |
| `overnight_hedge` module automation    | Manual hedge is the design. Not changing.                              |
| Multi-user Telegram support            | Single user only.                                                      |
| Angel One / alternate broker migration | Only if Dhan becomes unusable                                          |

---

## OPEN ITEMS (to be resolved in future sessions)

| #   | Item                                                       | Phase       | Status              |
| --- | ---------------------------------------------------------- | ----------- | ------------------- |
| O1  | GIFT Nifty symbol support on Dhan — needs live test        | Phase 0     | ⏳ Pending live test |
| O2  | `pin_totp` removal — broker auth moved to `access_token`   | Phase 0     | ✅ Completed         |
| O3  | Token hot-reload mechanism on token update                 | Phase 0     | ✅ Completed         |
| O4  | NSE 2027 holidays — add to `core/utils.py` before year-end | Maintenance | ⏳ Pending           |
| O5  | Dhan static IP — whitelist server IP at Dhan portal        | Production  | ⏳ Pending           |
| O6  | Flexible deployment design (expiry/strikes via Telegram)   | Phase 2     | 🔲 Not started       |

---

## SESSION LOG

| Date       | What was decided / designed                                                                                                            |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-18 | Created DESIGN.md (this file)                                                                                                          |
| 2026-03-18 | Locked 3-bot architecture: Drishti (infra/token) + Kavach (trading) + Lakshmi (MTM)                                                    |
| 2026-03-18 | Locked access token mode: manual JWT via Telegram, 24h expiry, abandoning pin_totp                                                     |
| 2026-03-18 | Locked Drishti bot design: token receipt flow, two alert types, quiet hours, GIFT Nifty                                                |
| 2026-03-18 | Locked reminder logic: suppressed when token valid, NSE holiday-aware, weekdays only                                                   |
| 2026-03-18 | Locked folder structure target: `bots/drishti/`, `bots/kavach/`, `bots/lakshmi/`                                                       |
| 2026-03-18 | Created batman_flowchart.html — visual end-to-end system flowcharts (9 diagrams)                                                       |
| 2026-04-24 | Added design for two additional operational modules: Run Readiness Orchestrator + Completion Orchestrator                              |
| 2026-04-24 | Closed run/end ownership questions: DRISHTI prompt ownership, KAVACH completion ownership, archival hard-stop rule                     |
| 2026-04-24 | Locked naming convention for overnight hedge lifecycle: RATRIPAL (buy/protect) + PRABHAT MUKTI (morning exit)                          |
| 2026-04-25 | Locked KAVACH register break-even confirmation design: auto-calc, user confirm/edit, multiple-of-50 validation, and weekly persistence |
| 2026-04-25 | Finalized BE edge-case defaults: missing avg price -> manual-only capture; BE alerts deferred (store now, alert later)                 |
| 2026-04-25 | Added Skip Break-even option with module gating: RATRIPAL/PRABHAT MUKTI disabled when BE is skipped; KAVACH ATO unaffected             |
| 2026-05-02 | Locked JAGRAN as the dedicated critical-incident bot; DRISHTI/KAVACH/RATRIPAL/PRABHAT MUKTI must publish high-priority errors to it    |

---

*Update this document at the start of every design session.
Add to SESSION LOG on every meeting. Add to OPEN ITEMS when new questions arise. Close items when resolved.*
