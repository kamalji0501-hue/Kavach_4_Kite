# INC-2026-STAB-02 — KAVACH menu reads wrong pause state in UAT

| Field | Value |
|-------|-------|
| Category | robot |
| Subsystem |  |
| Robot | kavach |
| Lifecycle | closed |
| Severity | high |
| Priority | p1 |
| Environment | uat |
| First observed | 2026-06-12 |
| Resolved | 2026-06-12 |
| Owner | agent |
| Last updated |  |
| Legacy STAB | STAB-02 |

## Symptoms

KAVACH menu reads wrong pause state in UAT

## Technical impact

Phase 1 reliability / feed / lifecycle

## Trading impact

ATO may not pause/resume correctly; feed outages; orphan processes

## Root cause

_read_algo_pause_reason() used default StateManager path

## Files / modules

- kavach-2.0/bat_telegram/bots/kavach2/bot.py

## Fix implemented

Use state_path(workspace_root())

## Why this fix works

Use state_path(workspace_root())

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

- INC-2026-STAB-01
