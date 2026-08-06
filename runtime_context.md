# Runtime Context — Trading_Runtime Separation

> **Updated:** 2026-08-06 (Rahul sandbox isolation)  
> **Code (Rahul sandbox):** `/home/ubuntu/rahul_Changes`  
> **Runtime (Rahul):** `/home/ubuntu/Trading_Runtime_Rahul`  
> **Code (Kamalji live):** `/home/ubuntu/batman-algo`  
> **Runtime (Kamalji live):** `/home/ubuntu/Trading_Runtime`  
> **Log layout (unchanged):** `Logs/{uat|prod}/runtime/YYYY-MM/YYYY-MM-DD/{bot}/...`  
> Do **not** adopt ChatGPT Year/Month/Date redesign. See `docs/TRADING_RUNTIME_RAHUL.md` and `docs/RUNTIME_AUDIT_20260806.txt`.

**Master reference** for runtime vs codebase layout after the 2026-07-27 migration.  
**Code root:** `/home/ubuntu/rahul_Changes`  
**Runtime root:** `/home/ubuntu/Trading_Runtime_Rahul`

---

## Why

Live trading generates logs, state, JWT caches, deployments, analytics, and secrets. Keeping those **inside** the git/code tree bloated the repo (~GB), risked committing secrets, and complicated VPS deploys (rsync of code vs preserve of state).

**Goal:** distributable **application only**; everything generated at runtime lives under **Trading_Runtime**.

**Non-goals:** no strategy, order, Telegram behaviour, or scheduler changes.

---

## Architecture (current)

```text
Batman Algo Files/
├── 15 July 26 DEV Batman Algo/DEV Batman Algo/   ← CODE (+ .venv)
│   ├── config/local_runtime.json                 ← absolute paths → Trading_Runtime
│   ├── kavach-2.0/config/local_runtime.json      ← SAME absolute paths
│   ├── core/batman_mode.py                       ← path API
│   ├── logs_runtime/   (legacy copy — do not use; rollback only)
│   └── data_runtime/   (legacy copy — do not use; rollback only)
└── Trading_Runtime/                              ← RUNTIME (outside code)
    ├── Logs/          ← logs_base()
    ├── Data/          ← data_reports_base()
    ├── Credentials/   ← secrets_root()
    ├── Temp/ Cache/ Backups/ Health/ Exports/
    ├── Screenshots/ Database/ User/ Config/
    └── Credentials/Tokens/
```

Internal **layout under Logs/Data is unchanged** (mode + dated windows):

```text
Logs/{uat|prod}/runtime/YYYY-MM/YYYY-MM-DD/{bot}/logs/...
Data/data/{mode}/batman_state.json
Data/data/{mode}/deployments/
Data/data/shared/access_token.json
Data/data/shared/nifty_ltp_cache.json
Credentials/config/.env
Credentials/telegram/bots/{bot}/token.env
```

---

## Configurable paths

| Mechanism | Keys / vars |
|-----------|-------------|
| `config/local_runtime.json` | `logs_root`, `data_reports_root`, `secrets_root` (absolute) |
| Env overrides | `BATMAN_LOGS_ROOT`, `BATMAN_DATA_REPORTS_ROOT`, `BATMAN_SECRETS_ROOT`, `BATMAN_RUNTIME_ROOT` |
| API | `core.batman_mode`: `logs_base`, `data_reports_base`, `secrets_root`, `data_root`, `state_path`, `access_token_path`, `ensure_runtime_layout`, `trading_runtime_umbrella` |

Resolution order: **env → local_runtime.json overlay on batman_mode.json → defaults**.

---

## Folder meanings

| Folder | Purpose |
|--------|---------|
| `Logs/` | All bot/runtime logs (existing year-month-day + bot hierarchy) |
| `Data/` | State, deployments, analytics, shared JWT/NIFTY cache, reports |
| `Credentials/` | Dhan `.env`, Telegram `token.env` (loader prefers this over in-repo) |
| `Credentials/Tokens/` | Optional token scratch (scaffold) |
| `Temp/` `Cache/` | Scratch / future cache relocation |
| `Backups/` `Health/` `Exports/` `Screenshots/` `Database/` `User/` `Config/` | Scaffold for ops artifacts |

---

## Migration (already run locally)

```bash
# Bots must be STOPPED
.venv/bin/python scripts/migrate_to_trading_runtime.py --dry-run
.venv/bin/python scripts/migrate_to_trading_runtime.py
```

Copies `logs_runtime` → `Logs`, `data_runtime` → `Data`, secrets → `Credentials`. **Does not delete** in-repo copies.

---

## Rollback

1. Stop all bots: `.venv/bin/python scripts/bot_status.py all` / stop scripts  
2. Restore `config/local_runtime.json` and `kavach-2.0/config/local_runtime.json` to:

```json
{
  "logs_root": "logs_runtime",
  "data_reports_root": "data_runtime",
  "secrets_root": "secrets_runtime"
}
```

(kavach-2.0 previously used `../logs_runtime`, `../data_runtime`, `secrets_runtime`)

3. Restart bots — they use in-repo trees again.  
4. Optional: re-copy newer files from Trading_Runtime back into `logs_runtime`/`data_runtime` if needed.

---

## Moving Trading_Runtime later

1. Stop bots.  
2. `mv` or `rsync` the whole `Trading_Runtime` tree to the new location.  
3. Update both `local_runtime.json` files (absolute paths).  
4. Or set env vars and leave JSON alone.  
5. `ensure_runtime_layout()` / smoke start.

---

## Local vs VPS (VPS not done yet)

| | Local (now) | VPS (future — needs approval) |
|--|-------------|-------------------------------|
| Code | `…/DEV Batman Algo` | `/home/ubuntu/batman-algo` |
| Runtime | `…/Batman Algo Files/Trading_Runtime` | `/home/ubuntu/Trading_Runtime` (proposed) |
| Config | absolute paths in `local_runtime.json` | same pattern + update `vps/deploy_to_vps.sh` JWT target |

**Do not deploy to VPS until operator approves.** Deploy script still hardcodes `$BATMAN_ROOT/data_runtime/...` for JWT copy — must be updated in VPS phase.

---

## Residual in-tree items (accepted for now)

- `backtest_engine/cache/` (~728M) — not live bot path  
- `Dependencies/` instrument CSVs + Tradehull `token_*.txt` day caches  
- `security_id_list.csv`  
- In-repo `telegram/bots/*/token.env` and `config/.env` — **fallbacks**; canonical is Credentials  
- Legacy `logs_runtime/` / `data_runtime/` copies — rollback only  

---

## Loader behaviour

`bat_telegram/loader.py`: try `secrets_bot_dir()/token.env` first, then in-repo `telegram/bots/.../token.env`.  
Dhan env: `secrets_dhan_env_path()` then `config/.env`.

---

## Related files

- `scripts/migrate_to_trading_runtime.py`  
- `MIGRATION_REPORT_Trading_Runtime.md`  
- `docs/MULTI_DEV_SETUP.md` (older Desktop layout notes)  
- `LOGGING_LAYOUT.md` (log window semantics — still valid under `Logs/`)  


---

## Rahul sandbox isolation (2026-08-06)

| Item | Value |
|------|--------|
| Sandbox code | `/home/ubuntu/rahul_Changes` |
| Sandbox runtime | `/home/ubuntu/Trading_Runtime_Rahul` |
| Config | `config/local_runtime.json` → Rahul runtime roots |
| Kamalji live runtime | `/home/ubuntu/Trading_Runtime` (unchanged) |
| Credentials seed | Copied once from Kamalji runtime Credentials |
| Logs/Data | Fresh under Rahul runtime (not copied) |

### Move Rahul runtime later

1. Stop bots using `rahul_Changes`.  
2. `rsync -a /home/ubuntu/Trading_Runtime_Rahul/ <newpath>/`  
3. Update `logs_root`, `data_reports_root`, `secrets_root` in sandbox `local_runtime.json` (+ kavach-2.0 twin, batman_mode path keys).  
4. Restart bots; confirm new log files under `<newpath>/Logs/uat/runtime/...`.

### Deploy notes

- Distributable package = code tree only (no `Trading_Runtime*`).  
- On any host: create runtime umbrella + point `local_runtime.json`.  
- Keep log semantics `mode/runtime/YYYY-MM/YYYY-MM-DD/bot` — do not redesign to Year/Month/Date without an explicit migration project.
