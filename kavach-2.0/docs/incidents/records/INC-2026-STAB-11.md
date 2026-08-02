# INC-2026-STAB-11 — Supervisor ignored LTP gate failure

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
| Legacy STAB | STAB-11 |

## Symptoms

Supervisor ignored LTP gate failure

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

LTP gate logged WARN only during market session

## Files / modules

- core/bot_supervisor.py

## Fix implemented

Abort Start All when LTP gate fails

## Why this fix works

Abort Start All when LTP gate fails

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
