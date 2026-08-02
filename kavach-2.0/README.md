# DEV Batman Algo

Live Batman options trading via **broker API** (not UI automation).

## Context docs

| Doc | Purpose |
|-----|---------|
| **`context/VPS_CONTEXT.md`** | SSH, test VPS, architecture, session log, production spec |
| **`context/VPS_OPS.md`** | Monitor, retry, stability test, deploy, cleanup |
| **`context/AGENT_QUICKSTART.md`** | Quick agent onboarding |
| **`context/README.md`** | Index |

## Key facts

- **Live orders:** broker API + JWT + static IP (whitelisted)
- **No Stockmock** for live trading — Stockmock is research/backtest only
- **Test VPS (friend's):** `3.110.255.216` — temporary; buy own VPS for production
- **Telegram:** alerts on trades, crashes, recovery
- **VPS monitor:** `vps_ops/` — auto-restart, retry, 100% stability test pass
- **Agent:** deploy, run, logs, debug via SSH from your PC

## VPS ops (deployed)

Local: `vps_ops/` → VPS: `/home/ubuntu/vps_ops/`

Services: `my_telegram_bot` + `vps-monitor` (both active)

*Last updated: 2026-07-10*
