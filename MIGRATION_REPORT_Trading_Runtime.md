# Migration Report — Trading_Runtime (2026-07-27)

## Summary

Separated Batman Phase-1 **runtime** (logs, data, credentials) from the **code** tree into:

`/home/kamalji0501e/Batman Algo Files/Trading_Runtime`

Preserved existing log/data folder **semantics** (mode + `YYYY-MM/YYYY-MM-DD/{bot}`). No trading strategy, order, or Telegram behaviour changes. Python `.venv` / package versions untouched. **VPS deploy not performed.**

## New architecture (tree)

```text
Trading_Runtime/
├── Logs/                 # ~200M migrated
├── Data/                 # ~66M migrated
├── Credentials/
│   ├── config/.env
│   ├── Tokens/
│   └── telegram/bots/{drishti,kavach,kavach2,jagran,saransh,ratripal,lakshmi}/token.env
├── Temp/ Cache/ Backups/ Health/ Exports/
├── Screenshots/ Database/ User/ Config/
```

## Modified files

| Path | Change |
|------|--------|
| `config/local_runtime.json` | Absolute Trading_Runtime paths |
| `kavach-2.0/config/local_runtime.json` | Same absolute paths |
| `core/batman_mode.py` (+ k2) | `trading_runtime_umbrella`, scaffold dirs in `ensure_runtime_layout` |
| `core/state.py` (+ k2) | Default state → `state_path()` |
| `core/token_store.py` (+ k2) | Default / legacy token → `access_token_path()` |
| `core/bot_supervisor.py` (+ k2) | Supervisor state under `data_root()` |
| `core/bot_health.py` (+ k2) | Health under `data_root()/runtime/` |
| `core/gift_nifty_ltp.py` (+ k2) | Cache under `shared_data_dir()` |
| `core/agent_feedback_loop.py` (+ k2) | Analytics under `data_root()` |
| `core/incident_fix_verification.py` (+ k2) | Reports under `data_root()` |
| `modules/ratripal.py` (+ k2) | ADITYA handoff under `data_root()/analytics/...` |
| `bat_telegram/bots/kavach/bot.py` (+ k2) | Deployments under `data_root()/deployments` |
| `kavach-2.0/bat_telegram/bots/kavach2/bot.py` | Same deployments path |
| `bat_telegram/bots/saransh/bot.py` (+ k2) | TokenStore → runtime path |
| `main.py` (+ k2) | TokenStore / StateManager / deployments via batman_mode |
| `.gitignore` | Ignore in-repo runtime dirs |

## Newly created files

| Path | Role |
|------|------|
| `scripts/migrate_to_trading_runtime.py` | One-shot copy migrate |
| `runtime_context.md` | Architecture master doc |
| `MIGRATION_REPORT_Trading_Runtime.md` | This report |
| `logs_runtime/README_LEGACY.md` | Stub pointer |
| `data_runtime/README_LEGACY.md` | Stub pointer |
| `Trading_Runtime/**` | External runtime tree |

## Migration guide

1. Stop bots.  
2. Ensure `local_runtime.json` points at Trading_Runtime (done).  
3. Run `scripts/migrate_to_trading_runtime.py` (done).  
4. Validate paths + smoke bots (see validation section).  
5. Keep in-repo `logs_runtime`/`data_runtime` until rollback window ends.

## Rollback guide

See `runtime_context.md` § Rollback — restore relative `local_runtime.json` and restart.

## Validation report

| Check | Result |
|-------|--------|
| Path API → Trading_Runtime | PASS (`logs_base`, `data_reports_base`, `secrets_root`, `state_path`, `access_token_path`) |
| Credentials present | PASS (all Phase-1 + RATRIPAL `token.env`, Dhan `.env`) |
| `ensure_runtime_layout` | PASS (20 path entries incl. scaffold) |
| `tests/test_ratripal.py` | PASS (6) |
| `kavach-2.0/tests/test_saransh_paths.py` | PASS |
| Smoke DRISHTI / KAVACH2 / JAGRAN / SARANSH | PASS — all RUNNING; logs under `Trading_Runtime/Logs/.../2026-07-28/{bot}/` |
| New writes to in-repo `logs_runtime` | NONE in smoke window |
| Bots stopped after smoke | PASS |

**Date:** 2026-07-27 (IST evening / log day folder 2026-07-28 post-midnight window)

## Remaining manual steps

- After Credentials proven for several sessions, optionally remove in-repo `token.env` / rely solely on Credentials (keep gitignored copies as backup).  
- **VPS:** wait for explicit approval; then create `/home/ubuntu/Trading_Runtime`, update remote `local_runtime.json`, fix `vps/deploy_to_vps.sh` JWT destination.  
- Later: relocate `Dependencies/token_*.txt` and `backtest_engine/cache` if desired.

## Risks

| Risk | Mitigation |
|------|------------|
| Dual write to old `data/` | Path defaults redirected; in-repo trees left but unused by helpers |
| kavach-2.0 path drift | Mirrored core + bot path files; shared absolute JSON |
| Secrets still in repo tree | Loader prefers Credentials; gitignore already covers token.env |
| VPS deploy script stale | Documented; do not deploy until Phase-2 |

## Recommendations

- Treat `runtime_context.md` as the single source of truth for paths.  
- Never commit `Trading_Runtime/` or `local_runtime.json` secrets (JSON paths are OK; Credentials are outside git).  
- Prefer env overrides on VPS for portability.  
