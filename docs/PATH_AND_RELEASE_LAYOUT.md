# Path & release layout (multi-VPS)

## Principle

| Layer | Lives where | Shipped in GitHub release? |
|-------|-------------|------------------------------|
| Core code (`core/`, `bat_telegram/`, `run_*.py`, templates) | VPS code tree | **Yes** |
| Secrets (Telegram, Dhan) | `<secrets_root>/` on that VPS | **No** |
| Logs / Data / caches / instrument dumps | runtime “desktop” | **No** |
| `.venv` | per VPS recreate | **No** |

On this sandbox:

- Code: `/home/ubuntu/rahul_Changes`
- Desktop/runtime: `/home/ubuntu/Trading_Runtime_Rahul`
  - `Credentials/telegram/bots.env` — **all Telegram bots for this VPS/user**
  - `Credentials/config/.env` — Dhan
  - `Logs/`, `Data/`, `MarketData/`, `Cache/`

Configured by `config/local_runtime.json` (paths only — not secrets).

## Telegram resolution (per VPS)

1. `<secrets_root>/telegram/bots.env` ← preferred (one file per machine)
2. `<secrets_root>/telegram/bots/<name>/token.env`
3. Repo `telegram/bots/<name>/token.env` (legacy fallback)
4. Process env

Different users ⇒ different `bots.env` on their VPS. Same code package.

## Smoke

```bash
.venv/bin/python scripts/smoke_telegram_bots.py
```

## Symlinks (local usability only)

`Dependencies`, `security_id_list.csv`, `backtest_engine/cache` → runtime. Do not put dumps back into git.
