# Verification — code lightening (2026-08-06)

## Goal
Keep releasable **code** in `/home/ubuntu/rahul_Changes`; keep dumps/caches/secrets in `/home/ubuntu/Trading_Runtime_Rahul`. **No strategy/broker logic changes.**

## Checks performed

| Check | Result |
|-------|--------|
| Code size excl. `.venv` (du without following links) | ~18 MB class |
| Moved CSV / security_id / cache under runtime | OK |
| Python readers of instrument/`security_id` paths | Comments only; TradeHull token dir = `Dependencies/` |
| `compileall` | exit 0 |
| Import core + four bot modules | OK |
| `build_application()` Drishti/Kavach/Jagran/Saransh | OK (after symlinks too) |
| Lighten `*.py` logic edits | **none** |
| Symlinks: relative paths → runtime; token write → runtime | OK |
| Four bot Telegram tokens under Credentials | Present |
| `access_token.json` | Not yet in Rahul runtime (expected until DRISHTI saves one) |

## Symlinks (usability, not shipping bulk)

- `Dependencies` → runtime MarketData/Dependencies
- `security_id_list.csv` → runtime MarketData
- `backtest_engine/cache` → runtime Cache
- Same under `kavach-2.0/`

## Logic consistency
No `.py` business logic modified for lightening. Logs/data/secrets still via `local_runtime.json`.
