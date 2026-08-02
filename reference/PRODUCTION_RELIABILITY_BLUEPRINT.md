# Batman v3 - Production Reliability Blueprint

Last updated: 2026-05-17
Audience: Rahul + operators preparing unattended VPS run in India market hours.

## Windows Execution Mode (2026-05-17)

Runtime target is Windows (not Linux/systemd) for current operations.

Use the smoke automation script before each major unattended run:

- Script: tools/vps-smoke-windows.ps1
- VS Code task: Ops: Windows VPS smoke

What it validates:

1. Preflight and Python/main entrypoint availability.
2. Write permissions for logs runtime, incidents, and deployment folders.
3. First startup health after warmup.
4. Runtime and module log file creation.
5. Controlled stop and restart behavior.
6. Runtime log growth after restart.
7. Presence check for incident artifacts (warn-only when no incidents happened).

Output location per run:

- data/analytics/vps_validation/[timestamp]/report.txt
- data/analytics/vps_validation/[timestamp]/report.json

## Objective

Run Batman safely and continuously on a VPS with deterministic behavior under broker/API instability, polling pressure, process restarts, and market volatility.

## Reliability Pillars

1. Process reliability
- Run Batman under service supervision (systemd/supervisor).
- Enable restart on crash and restart on reboot.
- Use restart backoff to avoid rapid crash loops.

2. Broker/API reliability
- Enforce polling discipline for NIFTY LTP checks.
- Fail fast on persistent broker errors and raise incident alerts.
- Keep trading logic idempotent so retries do not duplicate orders.

3. State and restart reliability
- Deployment file remains source of truth for active deployment.
- On startup, validate deployment vs broker positions before resuming ATO.
- If mismatch, transition to safe paused behavior and notify.

4. Observability and auditability
- Persist ATO execution telemetry to CSV for analysis and postmortems.
- Keep structured session/run logs and incident transitions.
- Ensure EOD summary consumes telemetry and flags data gaps.

## Polling and Rate-Limit Policy

Scope: NIFTY LTP polling for ATO loop.

1. Allowed per-deployment poll intervals
- 1 sec
- 2 sec
- 3 sec
- 4 sec
- 5 sec

2. Effective policy
- Default recommended for live run: 2 sec or 3 sec.
- Use 1 sec only when explicitly needed for high-sensitivity sessions.
- If broker/API instability is observed, shift to 3-5 sec and alert.

3. Guardrails
- Deployment-selected poll interval must be persisted and used by ATO loop.
- Missing deployment value falls back to config default.
- Polling changes must be visible in status and telemetry (`poll_interval_seconds_used`).

## EOD Summary Data Contract

At EOD (15:30 IST close window), SARANSH consumes KAVACH telemetry file:
- data/analytics/ato_execution_telemetry.csv

If missing/empty:
- Soft-fail telemetry section only.
- Publish remaining summary sections with explicit "telemetry unavailable" note.

## Failure Handling Policy

1. Soft-fail
- Telemetry write failure.
- Optional reporting section generation failure.
- Action: log + incident note; continue core execution.

2. Degrade
- Intermittent broker LTP fetch failures with recovery.
- Action: retry with bounded backoff; continue after recovery.

3. Safe pause
- Deployment/broker position mismatch on restart.
- Action: prevent blind execution and require operator verification.

4. Hard stop candidate
- Repeated order placement failures with unresolved broker errors.
- Action: pause affected side, raise immediate incident alert.

## Tomorrow Go-Live Confidence Plan

Target: decide if unattended VPS run is safe for next session.

### Entry Criteria (must pass)

1. Token and broker health
- DRISHTI token update successful.
- NIFTY LTP and balance checks stable.

2. Deployment and wizard correctness
- /register flow completes with expected values.
- Holiday review + side selections + polling interval saved.

3. ATO control behavior
- Correct trigger and retrace behavior on both sides (or selected side).
- No duplicate order attempts under retries.

4. Telemetry and summary path
- ATO telemetry CSV row append verified.
- SARANSH can read telemetry at EOD path.

### Large-Case Test Set (recommended before full unattended mode)

1. High-frequency pressure test
- Run with 1 sec polling for a controlled period.
- Verify no API throttling alerts and no loop starvation.

2. Restart recovery test
- Simulate process restart during active deployment.
- Verify restore, validation, and safe behavior on mismatch.

3. Burst event test
- Force rapid price movement scenario in simulator.
- Verify trigger/exit ordering, cycle counters, and no duplicate orders.

4. Broker transient failure test
- Inject temporary LTP/API failures.
- Verify bounded retries and incident alerts without state corruption.

5. EOD dependency test
- Ensure telemetry exists and is consumed by SARANSH.
- Verify fallback note if telemetry is intentionally removed.

## Decision Rule for Tomorrow

Mark as "GO" only if all of the following are true:
1. No unresolved High-severity failures in large-case tests.
2. Restart recovery behavior is deterministic.
3. Telemetry and EOD summary dependency path is validated.
4. Incident routing for critical failures is confirmed.

Else mark as "NO-GO" and run one more simulator cycle with fixes.

## Suggested First Live Settings (India market)

1. Poll interval: 2 sec (balanced sensitivity vs API load).
2. Keep both side-monitor and alerting enabled unless intentionally narrowed.
3. Keep service auto-restart enabled before carrying overnight risk.

## Immediate Next Actions

1. Run Windows VPS smoke script and capture report artifacts.
2. If failures exist, patch and re-run until FAIL=0.
3. Perform a small live smoke window before full unattended schedule.
