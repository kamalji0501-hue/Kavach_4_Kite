# INC-2026-STAB-01 — UAT state-file split-brain — ATO pause written to wrong path

| Field | Value |
|-------|-------|
| Category | configuration |
| Subsystem | algo_control |
| Robot | kavach |
| Lifecycle | closed |
| Severity | high |
| Priority | p1 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-01 |

## Symptoms

UAT state-file split-brain — ATO pause written to wrong path

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

pause_algo() used data/batman_state.json while UAT reads data/uat/batman_state.json

## Files / modules

- core/algo_control.py
- core/feed_recovery.py

## Fix implemented

default_state_path() → state_path(workspace_root()) mode-aware

## Why this fix works

default_state_path() → state_path(workspace_root()) mode-aware

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

- INC-2026-STAB-02

## Preventive measures

- All cross-bot state writes must use state_path() — never hard-code data/

## Lessons learned

- All cross-bot state writes must use state_path() — never hard-code data/
