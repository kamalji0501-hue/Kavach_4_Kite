# INC-2026-STAB-12 — health.json not authoritative for RUNNING

| Field | Value |
|-------|-------|
| Category | infrastructure |
| Subsystem |  |
| Robot | — |
| Lifecycle | closed |
| Severity | high |
| Priority | p1 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-12 |

## Symptoms

health.json not authoritative for RUNNING

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

classify_bot() ignored health heartbeat file

## Files / modules

- core/bot_health.py
- core/bot_process_status.py

## Fix implemented

health_confirms_running() upgrades status; stale heartbeat warnings

## Why this fix works

health_confirms_running() upgrades status; stale heartbeat warnings

## Regression risk

Re-test on UAT mode + feed failover after changes to listed modules

## Validation performed

- pytest stabilization subset
- scripts/stabilization_verify.py
- phase1_bot_check

## Stress testing

- 3-cycle stabilization_verify

## Validation cycles

3
