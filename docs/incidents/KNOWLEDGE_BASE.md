# Incident Knowledge Base

Permanent operational lessons from the Batman incident registry.  
**Registry:** `docs/incidents/registry.json` · **Dashboard:** `docs/incidents/REGISTRY.md`

---

## WebSocket disconnects and false failovers

**Symptoms:** ATO auto-paused `nifty_ltp_websocket_failed` shortly after “WebSocket connected”; REST fallback while ticks appear in `ws_ltp_*.log`.

**Root causes seen:**
- Dhan v2 `Previous Close` control frames treated as errors (**INC-2026-STAB-04**)
- HTTP 429 without cooldown → reconnect storm (**INC-2026-STAB-05**, **STAB-06**)
- Stale watchdog fired before first post-reconnect tick (**INC-2026-017**)

**Fix pattern:** Skip non-LTP frames; rate-limit cooldown; `mark_transport_started()` + 30s transport grace after WS connect.

**Ops:** Check `logs_uat/.../drishti/logs/nifty_websocket_ltp/ws_ltp_YYYYMMDD.log` before trusting failover Telegram alerts.

---

## Token expiration and feed gating

**Symptoms:** “Token expired” at startup; feed starts then Dhan rejects JWT.

**Root causes:**
- `saved_at` age vs JWT `exp` mismatch (**INC-2026-STAB-07**)
- Auth errors retried as connection failures (**INC-2026-STAB-09**)

**Fix pattern:** `TokenStore.is_effectively_expired()` gates feed; `on_auth_failure` blocks failover/retry.

**Ops:** Refresh JWT via DRISHTI Update Token; confirm Health shows `fundlimit: OK`.

---

## UAT state path split-brain

**Symptoms:** DRISHTI pauses ATO but KAVACH Resume still enabled / wrong menu state.

**Root cause:** `pause_algo()` wrote `data/batman_state.json` while UAT bots read `data/uat/batman_state.json` (**INC-2026-STAB-01**, **STAB-02**).

**Rule:** Always use `state_path(workspace_root())` — never hard-code `data/batman_state.json`.

---

## UAT fixture / ShadowBroker expiry

**Symptoms:** `No NIFTY PE strike … for expiry YYYY-MM-DD in instrument master` at KAVACH/SARANSH startup.

**Root cause:** `uat/deployed_positions/positions.json` weekly expiry passed; instrument master drops expired series (**INC-2026-016**).

**Fix pattern:** `resolve_fixture_trading_expiry()` auto-rolls to nearest valid weekly; clear `shadow_order_ledger.json` on roll (**INC-2026-019**).

**Ops:** Paste fresh Sensibull screenshot after weekly expiry; run `backtest_engine/tools/validate_fixture.py`.

---

## Startup sequencing and lifecycle

**Symptoms:** ORPHAN locks, duplicate PIDs, Start All spawns KAVACH without LTP.

**Fixes:** Tier 1–3 lifecycle (**STAB-08**); supervisor LTP gate abort (**STAB-11**); `health.json` confirms RUNNING (**STAB-12**); KAVACH lazy JWT bootstrap (**STAB-10**).

**Ops:** Only `Execution\Start Bots\` / `Stop Bots\` — never close CMD with X. Run `Show Bot Status.bat` before Start All.

---

## Observability pitfalls

| Issue | Lesson | Incident |
|-------|--------|----------|
| `diagnose_robot` shows 0 B logs in UAT | Use `log_runtime_root()` — mode-aware | INC-2026-018 |
| E2E log scan fails after fix | Scope to latest session (`Batman mode:` marker) | INC-2026-020 |
| State save fails on first run | `StateManager.save()` must mkdir parent | INC-2026-STAB-15 |

---

## Configuration best practices

1. **Mode-aware paths** — `get_mode()`, `data_root()`, `log_root()`, `state_path()`
2. **Validate fixture after OCR/chat ingest** — `validate_fixture.py`
3. **≥2 validation cycles** before closing production-impacting incidents
4. **Search before filing** — `scripts/incident_mgmt.py search "<error>"`

---

*Grows automatically when incidents close — run `incident_mgmt.py export` after registry edits.*
