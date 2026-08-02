# INC-2026-STAB-03 — Failover state lost on DRISHTI restart

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
| Legacy STAB | STAB-03 |

## Symptoms

Failover state lost on DRISHTI restart

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

WS→REST session lock lived only in app.bot_data

## Files / modules

- core/nifty_ltp_failover.py

## Fix implemented

Persist failover to batman_state.json key nifty_ltp_failover

## Why this fix works

Persist failover to batman_state.json key nifty_ltp_failover

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
