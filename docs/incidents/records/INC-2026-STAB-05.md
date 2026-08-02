# INC-2026-STAB-05 — WebSocket HTTP 429 reconnect storm

| Field | Value |
|-------|-------|
| Category | market_data |
| Subsystem |  |
| Robot | drishti |
| Lifecycle | closed |
| Severity | critical |
| Priority | p0 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-05 |

## Symptoms

WebSocket HTTP 429 reconnect storm

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

429 incremented failure counter → false failover

## Files / modules

- core/nifty_ltp_websocket_feed.py

## Fix implemented

429 cooldown; do not increment consecutive_failures

## Why this fix works

429 cooldown; do not increment consecutive_failures

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

## Related incidents

- INC-2026-STAB-06
