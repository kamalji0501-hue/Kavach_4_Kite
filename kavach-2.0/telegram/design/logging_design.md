# Logging and Incident Ledger Design (LOCKED - 2026-05-16)

## Scope (Phase 1)

- Runtime scope: MAIN + DRISHTI + KAVACH + JAGRAN.
- This is a design-only specification. Coding starts only after explicit sign-off.

## Objectives

- Keep logs human-readable for rapid debugging.
- Preserve module-wise execution traceability.
- Maintain daily incident/recovery audit records.
- Keep runtime logging text-first to avoid lock/read friction.

## Runtime Log Line Format

Each log entry is one line:

`HHMMSS.mmm IST | LEVEL | MODULE | STAGE | STEP | CORRELATION_ID | MESSAGE | ERROR_CODE(optional)`

Locked rules:

1. Timezone is IST only.
2. Milliseconds are mandatory.
3. One log event per line.
4. INFO and ERROR are primary levels.
5. WARN remains optional/secondary.
6. Step numbers are included for flow logs.
7. Date is intentionally omitted from each line because date is encoded in folder path.

## Folder Layout

Base pattern:

`<root>/YYYY-MM/YYYY-MM-DD/`

Inside each date folder:

- `logs/`
- `drishti/`
- `kavach/`
- `lakshmi/`
- `jagran/`

Notes:

1. Active bot folders only.
2. Runtime text logs are stored only in `logs/`.
3. Bot folders store bot-specific artifacts/outputs.

## Log File Segmentation

### Creation policy

- Files are created on demand per window.
- No pre-creation of all daily files.

### Window policy

1. Hourly windows across 24 hours.
2. Special close split:
1. `15:00-15:30`
2. `15:30-16:00`
3. Post-market uses segmented files (not one single post-market file).
4. Post-market classification applies from `15:30` through next-day `08:59`.

### Naming examples

- `runtime_20260516_0900_1000.log`
- `runtime_20260516_1500_1530.log`
- `runtime_20260516_post_1530_1600.log`
- `runtime_20260516_post_1600_1700.log`
- `drishti_20260516_0900_1000.log`
- `kavach_20260516_1500_1530.log`

## Main + Module Sink Strategy

Locked approach:

1. Write directly to both sinks at event time (main + relevant module file).
2. Main log is canonical timeline.
3. Module logs mirror the same format for local debugging.
4. If log writing fails, trading flow must continue and a critical incident is raised.

## Incident Flow Traceability

Recommended lifecycle markers:

- START
- CHECKPOINT
- ACTION
- SUCCESS
- FAIL
- END

On error routes, include next-hop marker when applicable:

- `NEXT_HANDLER=JAGRAN`

JAGRAN must log both:

1. Incident receive event.
2. Delivery outcome event.

## Correlation ID Policy

Format:

- `DRI-YYYYMMDD-HHMMSS-####`
- `KAV-YYYYMMDD-HHMMSS-####`
- `JAG-YYYYMMDD-HHMMSS-####`
- `MAIN-YYYYMMDD-HHMMSS-####`

Counter policy:

- Counter resets daily.

## Incident Ledger Policy

### Behavior

1. Every incident is recorded.
2. Every recovery is recorded.
3. Repeated incidents are recorded with fresh timestamps and repeat count.
4. Dedup-suppressed notification attempts are recorded with explicit suppressed status.
5. Delivery failures are recorded as separate ledger events.

### Storage/output

Primary runtime stream:

- Text-based append-safe incident ledger stream.

End-of-day outputs:

- Excel workbook (primary review output).
- Optional CSV companion export.

Workbook sheets:

1. `Incidents`
2. `Recoveries`
3. `Combined`

### Export retry policy

1. Retry interval is config-driven.
2. Design default retry interval: 3 minutes.
3. Max attempts: config-driven (design default: 3).
4. After max attempts, emit final error and stop retry loop for that cycle.

## Severity and Categories

Severity values:

- critical
- major
- minor

Categories:

- Config-driven labels.

## Configuration Strategy

All logging and ledger tunables must be changeable via config without code edits.

Design decision:

1. Canonical source: `config/settings.json`.
2. Optional per-bot overrides where params files already exist.

## Retention and Safety Policy

1. Append-only behavior.
2. No compression.
3. Unlimited retention (operational cleanup handled externally).

## Privacy Policy

Owner-approved for this deployment:

- No masking required.
- Raw values may be logged as-is.

Operational caution remains documented for future hardened environments.

## Non-Goals (Phase 1)

1. Historical log migration.
2. PRABHAT MUKTI and RATRIPAL logging expansion.
3. Simulator parity for this logging architecture.

## Implementation Readiness

Execution order after sign-off:

1. Logger infrastructure + formatter.
2. Time-window file router.
3. Main + module dual sink wiring.
4. Incident stream writer.
5. EOD workbook generator.
6. Config bindings.
7. Tests and regression checks.
