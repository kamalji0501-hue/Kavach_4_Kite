# INC-2026-STAB-09 — Auth errors retried and triggered failover

| Field | Value |
|-------|-------|
| Category | broker |
| Subsystem |  |
| Robot | drishti |
| Lifecycle | closed |
| Severity | high |
| Priority | p1 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-09 |

## Symptoms

Auth errors retried and triggered failover

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

HTTP 401 treated as connection error

## Files / modules

- core/nifty_ltp.py
- core/nifty_ltp_feed.py
- core/nifty_ltp_websocket_feed.py

## Fix implemented

is_auth_error() + on_auth_failure — no retry, no failover

## Why this fix works

is_auth_error() + on_auth_failure — no retry, no failover

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
