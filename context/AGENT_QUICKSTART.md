# Agent Quickstart — DEV Batman Algo

> Read **[VPS_CONTEXT.md](VPS_CONTEXT.md)** and **[VPS_OPS.md](VPS_OPS.md)** before VPS work.  
> **Project root:** `H:\RK Data\Algo Trading Parent\DEV Batman Algo`

---

## What this project is

**Live Batman options algo** — place real orders via **broker API** when conditions are met.

| In scope | Out of scope |
|----------|--------------|
| Broker API orders (JWT / session token) | Stockmock UI automation |
| Condition check → entry ~11:00 IST → exit ~15:15 IST | Browser / Playwright for live trading |
| Telegram alerts on trades and errors | Using friend's VPS as permanent production |
| VPS deployment (Ubuntu, systemd, logs) | Placing orders through Stockmock website |
| VPS monitor + auto-recovery (`vps_ops/`) | |

**Stockmock scraper** (`Stockmock 11.00 PM vs 3.15 PM Batman Deployment`) is a **separate research project** for Excel backtest data only.

---

## User preference

User wants **hands-off operation** — agent handles coding, testing, deployment, monitoring, debugging, and log review via SSH. User should not need to log into VPS or manage day-to-day ops.

---

## VPS status (2026-07-10)

| Item | Value |
|------|-------|
| **Test VPS** | Friend's AWS Lightsail — `3.110.255.216` (borrowed, not production) |
| **SSH** | `ubuntu@3.110.255.216` |
| **Key** | `E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem` |
| **OpenSSH** | Installed on Windows (Admin PowerShell) |
| **Proved** | SSH, Python, Telegram, crash recovery |
| **Services** | `my_telegram_bot` + `vps-monitor` both **active** |
| **Stability** | 10-iteration test — **100% pass rate** |
| **Production** | User will buy own VPS with **static IP** for broker whitelist |

---

## Agent checklist for VPS work

1. SSH from user's Windows PC (OpenSSH installed)
2. Deploy to `~/batman-algo/` on **user's own VPS** (not friend's long-term)
3. Use broker API only — no UI automation
4. Wire Telegram via `telegram_notify.py` or `vps_ops/notifier.py` pattern
5. Set up systemd timer for market hours (11:00 / 15:15 IST)
6. Add Batman service to `vps-monitor` `WATCHED_SERVICES`
7. Automate JWT/session token refresh before unattended runs
8. Log everything; alert on failure via Telegram
9. Redeploy ops: `vps_ops/deploy_and_test.sh` on VPS

---

## Key paths

| Path | Role |
|------|------|
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo` | Main project — live API Batman |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\context\VPS_CONTEXT.md` | Full VPS reference |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\context\VPS_OPS.md` | Monitor, retry, stability, deploy |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\vps_ops\` | Ops code (local source) |
| `/home/ubuntu/vps_ops/` | Ops code (deployed on test VPS) |
| `E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem` | Friend's test VPS key |

---

## Problems fixed (2026-07-10)

- Duplicate `telegrambot.service` → removed
- 29 MB log → truncated + rotation
- Hardcoded Telegram token → `.env` only
- No crash recovery → `vps-monitor.service`
- Test Stockmock folder on VPS → removed
- Stability verified → 10/10 pass

**Still pending:** Breeze JWT auto-refresh, own production VPS.
