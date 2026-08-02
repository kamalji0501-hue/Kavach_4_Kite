# Reliability Engineering Report

**Generated:** 2026-06-25T16:22:01.421156+05:30
**Source artifact:** `data\analytics\reliability\phase1_reliability_20260625_155803.json`
**Run ID:** 20260625_155803
**Overall:** PASS

**Off-hours sign-off (2026-06-25):** 5/5 + 2/2 lifecycle cycles PASS with `post_market` LTP gate skip. Full pytest PASS. Stabilization + MCX probe PASS. Live NIFTY/WebSocket proof deferred — see checklist below.

**Latest artifacts:**
- `data/analytics/reliability/phase1_reliability_20260625_155803.json` (5 cycles)
- `data/analytics/reliability/phase1_reliability_20260625_165603.json` (2 cycles)

**Tomorrow:** Regenerate after 15-cycle market-hours run via `scripts/generate_reliability_engineering_report.py`.

## Market session

- Live LTP required: `False`
- LTP gate skip reason: `post_market`

## Cycle results

| Cycle | Startup | Robots | Price | Telegram | Shutdown | Status |
|-------|---------|--------|-------|----------|----------|--------|
| 1 | OK | OK | OK | OK | OK | PASS |
| 2 | OK | OK | OK | OK | OK | PASS |
| 3 | OK | OK | OK | OK | OK | PASS |
| 4 | OK | OK | OK | OK | OK | PASS |
| 5 | OK | OK | OK | OK | OK | PASS |

## Per-cycle detail

### Cycle 1

- **final_status:** PASS
- **price_flow_mode:** off_hours_post_market_last_cache_ok
- **start_elapsed_s:** 129.38
- **stop_elapsed_s:** 51.33
- **warnings:** live_nifty_validation_skipped:post_market, unexpected_log_patterns_detected

### Cycle 2

- **final_status:** PASS
- **price_flow_mode:** off_hours_post_market_last_cache_ok
- **start_elapsed_s:** 175.86
- **stop_elapsed_s:** 54.16
- **warnings:** live_nifty_validation_skipped:post_market, unexpected_log_patterns_detected

### Cycle 3

- **final_status:** PASS
- **price_flow_mode:** off_hours_post_market_last_cache_ok
- **start_elapsed_s:** 149.34
- **stop_elapsed_s:** 47.55
- **warnings:** live_nifty_validation_skipped:post_market, unexpected_log_patterns_detected

### Cycle 4

- **final_status:** PASS
- **price_flow_mode:** off_hours_post_market_last_cache_ok
- **start_elapsed_s:** 143.67
- **stop_elapsed_s:** 47.58
- **warnings:** live_nifty_validation_skipped:post_market, unexpected_log_patterns_detected

### Cycle 5

- **final_status:** PASS
- **price_flow_mode:** off_hours_post_market_last_cache_ok
- **start_elapsed_s:** 159.72
- **stop_elapsed_s:** 47.41
- **warnings:** live_nifty_validation_skipped:post_market, unexpected_log_patterns_detected

## Deferred (market hours)

See `docs/RELIABILITY_MARKET_HOURS_DEFERRED.md` for live NIFTY/WebSocket validation.

## Failure inventory

See `docs/RELIABILITY_FAILURE_INVENTORY.md`.

