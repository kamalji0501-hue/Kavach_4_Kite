# INC-2026-STAB-15 — Lock timeout without retry on state writes

| Field | Value |
|-------|-------|
| Category | runtime |
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
| Legacy STAB | STAB-15 |

## Symptoms

Lock timeout without retry on state writes

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

exclusive_file_lock() single attempt under concurrent writes

## Files / modules

- core/process_lock.py
- core/state.py

## Fix implemented

retries=3 with backoff on TimeoutError; state.save mkdir parent

## Why this fix works

retries=3 with backoff on TimeoutError; state.save mkdir parent

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
