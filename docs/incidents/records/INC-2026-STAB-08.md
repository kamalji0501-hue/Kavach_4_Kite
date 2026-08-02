# INC-2026-STAB-08 — Startup lock / PID reuse failures

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
| Legacy STAB | STAB-08 |

## Symptoms

Startup lock / PID reuse failures

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

Plain PID locks; UAT lock path mismatch

## Files / modules

- core/instance_lock.py
- core/bot_lifecycle.py
- core/bot_supervisor.py

## Fix implemented

Tier 1+2 lifecycle hardening + reconcile

## Why this fix works

Tier 1+2 lifecycle hardening + reconcile

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
