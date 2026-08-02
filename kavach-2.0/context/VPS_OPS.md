# VPS Operations — Monitor, Retry, Stability

> **Deployed to:** `/home/ubuntu/vps_ops/` on test VPS  
> **Local source:** `H:\RK Data\Algo Trading Parent\DEV Batman Algo\vps_ops\`  
> **Last updated:** 2026-07-10

---

## What this does

Production-grade VPS reliability layer for Telegram bot (and future Batman API services):

- **Crash detection** — watches systemd units every 15s
- **Auto-recovery** — kill stale PID → restart with exponential backoff (5 retries)
- **Feedback loop** — writes `state/monitor_state.json`, logs to `logs/monitor.log`
- **Telegram alerts** — crash detected, recovery success, recovery failed
- **Log rotation** — bot uses RotatingFileHandler + system logrotate
- **Stability testing** — `run_stability_test.py` kills service N times, measures recovery

---

## Files (local → VPS)

| File | Purpose |
|------|---------|
| `service_monitor.py` | Main watchdog daemon |
| `run_stability_test.py` | Kill/recover test runner (default 10 iterations) |
| `bot.py` | Fixed Telegram bot (rotating logs, `.env` token) |
| `notifier.py` | Fixed notifier (`.env` only, no hardcoded token) |
| `my_telegram_bot.service` | Improved systemd unit for bot |
| `vps-monitor.service` | systemd unit for watchdog |
| `logrotate-telegram` | logrotate config |
| `sudoers-vps-monitor` | Passwordless `systemctl restart` for monitor |
| `deploy_and_test.sh` | One-shot cleanup + deploy + stability test |

---

## Services on VPS (after deploy)

| Service | Status | Role |
|---------|--------|------|
| `my_telegram_bot.service` | **active** | Telegram incoming message bot |
| `vps-monitor.service` | **active** | Crash watch + auto-recover |
| `telegrambot.service` | **removed** | Was duplicate — caused Conflict errors |

---

## Stability test results (2026-07-10)

**10 iterations** — kill bot process, verify auto-recovery:

| Metric | Value |
|--------|-------|
| Pass rate | **100%** (10/10) |
| Avg recovery | **21.14 sec** (most runs ~6 sec; iteration 10 slower) |
| Results file | `/home/ubuntu/vps_ops/state/stability_results.json` |
| Monitor state | `/home/ubuntu/vps_ops/state/monitor_state.json` |

Per-iteration recovery times: 4.07, 6.06, 6.11, 6.05, 6.06, 6.05, 6.06, 1.03, 6.06, 163.84 sec

---

## Monitor configuration (env vars)

Set in `vps-monitor.service`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `WATCHED_SERVICES` | `my_telegram_bot.service` | Comma-separated units to watch |
| `MONITOR_MAX_RETRIES` | `5` | Recovery attempts per crash |
| `MONITOR_RETRY_BASE_SEC` | `3` | Base delay (exponential backoff) |
| `MONITOR_CHECK_INTERVAL` | `15` | Seconds between health checks |
| `TELEGRAM_ENV_PATH` | `/home/ubuntu/my_telegram_bot/.env` | Telegram credentials |

---

## Redeploy commands

**From Windows:**

```powershell
$key = "E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem"
scp -i $key -r "H:\RK Data\Algo Trading Parent\DEV Batman Algo\vps_ops" ubuntu@3.110.255.216:/home/ubuntu/
```

**On VPS:**

```bash
sed -i 's/\r$//' /home/ubuntu/vps_ops/deploy_and_test.sh
bash /home/ubuntu/vps_ops/deploy_and_test.sh
```

**Manual service checks:**

```bash
systemctl status my_telegram_bot vps-monitor
journalctl -u vps-monitor -n 30 --no-pager
tail -f /home/ubuntu/vps_ops/logs/monitor.log
cat /home/ubuntu/vps_ops/state/monitor_state.json
```

**Re-run stability test only:**

```bash
cd /home/ubuntu/vps_ops && ./venv/bin/python run_stability_test.py 10
```

---

## Cleanup performed (2026-07-10)

| Item | Action |
|------|--------|
| `telegrambot.service` | Stopped, disabled, masked, unit file deleted |
| `telegram_bot.log` (~29 MB) | Truncated; now rotating (5 MB × 3 backups) |
| `notifier.py` hardcoded token | Replaced with `.env` lookup |
| `~/stockmock-batman-src/` | Removed (test deploy only) |
| logrotate | Installed at `/etc/logrotate.d/vps-telegram` |
| sudoers | `/etc/sudoers.d/vps-monitor` for passwordless restart |

---

## Still pending (not in vps_ops)

| Item | Notes |
|------|-------|
| Breeze `SESSION_TOKEN` ~24h expiry | Needs separate token-refresh automation for live Batman |
| Own production VPS | Friend's server is test only |
| Batman API algo deploy | Deploy to `~/batman-algo/` when ready; add to `WATCHED_SERVICES` |

---

## Adding Batman service to monitor (future)

When Batman API algo has a systemd unit e.g. `batman-algo.service`:

1. Edit `vps-monitor.service` → `WATCHED_SERVICES=my_telegram_bot.service,batman-algo.service`
2. Add sudoers lines for `batman-algo.service` restart
3. `sudo systemctl daemon-reload && sudo systemctl restart vps-monitor`
