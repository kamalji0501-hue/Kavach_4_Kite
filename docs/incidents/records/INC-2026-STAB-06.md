# INC-2026-STAB-06 — WS 429 cooldown exceeded stale threshold → false failover

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
| Legacy STAB | STAB-06 |

## Symptoms

WS 429 cooldown exceeded stale threshold → false failover

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

Stale watchdog ignored rate_limit_until during cooldown

## Files / modules

- core/nifty_ltp_feed.py
- core/nifty_ltp_websocket_feed.py

## Fix implemented

Skip stale alerts during rate-limit cooldown; refresh last_update_at on 429

## Why this fix works

Skip stale alerts during rate-limit cooldown; refresh last_update_at on 429

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

- INC-2026-017
- INC-2026-STAB-05
