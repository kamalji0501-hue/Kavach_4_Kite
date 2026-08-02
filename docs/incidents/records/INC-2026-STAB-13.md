# INC-2026-STAB-13 — Session REST lock with no same-day WS retry

| Field | Value |
|-------|-------|
| Category | market_data |
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
| Legacy STAB | STAB-13 |

## Symptoms

Session REST lock with no same-day WS retry

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

session_rest_lock_date blocked WS without retry path

## Files / modules

- core/nifty_ltp_failover.py
- bat_telegram/bots/drishti/nifty_feed_integration.py

## Fix implemented

try_websocket_retry_after_rest() every 15 min

## Why this fix works

try_websocket_retry_after_rest() every 15 min

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
