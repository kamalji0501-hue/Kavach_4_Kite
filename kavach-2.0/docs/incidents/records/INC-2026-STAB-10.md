# INC-2026-STAB-10 — KAVACH cold-start without JWT

| Field | Value |
|-------|-------|
| Category | robot |
| Subsystem |  |
| Robot | kavach |
| Lifecycle | closed |
| Severity | high |
| Priority | p1 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-10 |

## Symptoms

KAVACH cold-start without JWT

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

token_watch skipped when broker was None at startup

## Files / modules

- core/token_watch.py
- run_kavach2.py

## Fix implemented

Lazy bootstrap via on_token_ready callback

## Why this fix works

Lazy bootstrap via on_token_ready callback

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
