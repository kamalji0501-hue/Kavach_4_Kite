# What belongs in a release vs runtime

**Code tree (`/home/ubuntu/rahul_Changes`):** source, config templates, requirements, tests, bot runners.
**Runtime (`/home/ubuntu/Trading_Runtime_Rahul`):** credentials, logs, data, market dumps, caches, screenshots, archives.

## Relocated out of code (2026-08-06)

| From code tree | Now under |
|----------------|-----------|
| Instrument CSVs / Dependencies dumps | `Trading_Runtime_Rahul/MarketData/Dependencies/` |
| `security_id_list.csv` | `Trading_Runtime_Rahul/MarketData/` |
| `backtest_engine/cache/` | `Trading_Runtime_Rahul/Cache/backtest_engine/` |
| Screenshots / Prod Data / in-repo `data/` | `Trading_Runtime_Rahul/Screenshots|Data/...` |
| Same for `kavach-2.0/` dumps | `.../kavach-2.0/` subfolders under MarketData/Cache |

## Never ship to customer VPS

- `.venv/` (recreate with pip on each host)
- MarketData dumps, caches, logs, credentials
- Nested bulky archives

## Multi-VPS release recipe

1. Sync/copy **code only** (exclude `.venv`, `Dependencies/*csv`, caches).
2. On target: create `Trading_Runtime_*`, set `local_runtime.json`.
3. Place secrets under `Credentials/`.
4. `python3 -m venv .venv && pip install -r requirements…`.
5. Start bots.

## Local VPS convenience symlinks (not the data itself)

On this host, these names in the code tree are **symlinks into runtime** so relative paths keep working without storing dumps in git:

- `Dependencies` → `Trading_Runtime_Rahul/MarketData/Dependencies`
- `security_id_list.csv` → `Trading_Runtime_Rahul/MarketData/security_id_list.csv`
- `backtest_engine/cache` → runtime Cache path
- same pattern under `kavach-2.0/`

Release sync should **not** copy symlink targets; recreate empty dirs or symlinks on each VPS after deploy.
