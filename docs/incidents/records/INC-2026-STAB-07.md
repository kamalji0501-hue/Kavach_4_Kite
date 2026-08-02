# INC-2026-STAB-07 — Feed gating used save-age only, not JWT exp

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
| Legacy STAB | STAB-07 |

## Symptoms

Feed gating used save-age only, not JWT exp

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

is_expired() vs effective JWT expiry mismatch

## Files / modules

- core/token_store.py
- bat_telegram/bots/drishti/nifty_feed_integration.py

## Fix implemented

is_effectively_expired() gates feed start

## Why this fix works

is_effectively_expired() gates feed start

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
