# INC-2026-STAB-14 — Live Price opened parallel one-shot WebSocket

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
| Legacy STAB | STAB-14 |

## Symptoms

Live Price opened parallel one-shot WebSocket

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

Handler always opened new WS while background feed active

## Files / modules

- bat_telegram/bots/drishti/nifty_feed_integration.py

## Fix implemented

Prefer fresh cache when background feed healthy

## Why this fix works

Prefer fresh cache when background feed healthy

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
