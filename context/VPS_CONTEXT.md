# VPS Context — DEV Batman Algo (API Live Trading)

> **Purpose:** Single reference for VPS setup, testing, SSH access, monitoring, and lessons learned.  
> **Project root:** `H:\RK Data\Algo Trading Parent\DEV Batman Algo`  
> **Use when:** Deploying Batman live algo (broker API orders), not Stockmock UI scraping.  
> **Last updated:** 2026-07-10 (night — VPS ops deploy, monitor, stability test complete)  
> **See also:** [VPS_OPS.md](VPS_OPS.md) — monitor, retry, deploy commands, test results

---

## Table of contents

1. [Project split — what goes where](#project-split--what-goes-where)
2. [Important: test VPS is a friend's server](#important-test-vps-is-a-friends-server)
3. [Local PC setup (Windows)](#local-pc-setup-windows)
4. [Test VPS details (2026-07-10)](#test-vps-details-2026-07-10)
5. [What we accomplished today](#what-we-accomplished-today)
6. [What belongs on VPS for live Batman](#what-belongs-on-vps-for-live-batman)
7. [What was already on the test VPS](#what-was-already-on-the-test-vps)
8. [Problems and issues found](#problems-and-issues-found)
9. [VPS recommendation for production](#vps-recommendation-for-production)
10. [How the agent connects and manages VPS](#how-the-agent-connects-and-manages-vps)
11. [What the agent can and cannot do](#what-the-agent-can-and-cannot-do)
12. [SSH commands cheat sheet](#ssh-commands-cheat-sheet)
13. [Telegram integration](#telegram-integration)
14. [Next steps when you get your own VPS](#next-steps-when-you-get-your-own-vps)
15. [VPS ops — monitor and stability](#vps-ops--monitor-and-stability)
16. [Session log](#session-log--2026-07-10)

---

## Project split — what goes where

| Project | Path (local) | Purpose | VPS needed? |
|---------|--------------|---------|-------------|
| **DEV Batman Algo** | `H:\RK Data\Algo Trading Parent\DEV Batman Algo` | **Live trading** — place orders via **broker API** when conditions met (11:00 entry, 15:15 exit, etc.) | **Yes — main production target** |
| **Stockmock Batman scraper** | `H:\RK Data\Algo Trading Parent\Stockmock 11.00 PM vs 3.15 PM Batman Deployment` | **Research only** — UI automation on Stockmock.in for backtest Excel data | Optional; not for live orders |

**Live Batman flow (this project):**

```
VPS (Ubuntu, static IP, ap-south-1 Mumbai)
  → systemd timer / cron at market hours
  → check Batman conditions
  → broker API (JWT / session token)
  → place / exit orders
  → Telegram alert on success or failure
  → logs to file
```

**Hard rules:**

- **No UI automation** for live Batman
- **No Stockmock** for placing live orders
- **Broker API only** — JWT token + **static IP** whitelisted with broker
- **Telegram** for monitoring and alerts

---

## Important: test VPS is a friend's server

The VPS used on **2026-07-10** belongs to a **friend**. Borrowed for connectivity and capability testing only — **not** permanent Batman production.

| Do | Don't |
|----|-------|
| Use notes in this file for your **own** VPS later | Treat friend's VPS as permanent production |
| Copy patterns (SSH, Telegram, systemd) | Leave long-running Batman live jobs on friend's box without agreement |
| Purchase your own Lightsail/EC2 with **static IP** for broker whitelist | Assume friend's IP/key will always be available |

When you buy your own VPS: **static IP → whitelist with broker → deploy DEV Batman Algo**.

---

## Local PC setup (Windows)

Everything needed on user's PC for agent to manage VPS:

| Component | Status | Notes |
|-----------|--------|-------|
| **Python** | OK | 3.12.9 |
| **pip** | OK | Upgraded during session |
| **OpenSSH Client** | OK | Installed 2026-07-10 via Admin PowerShell |
| **Git SSH** | OK | Fallback at `C:\Program Files\Git\usr\bin\ssh.exe` |
| **`.ssh` folder** | OK | `C:\Users\RK\.ssh` |
| **Cursor extensions** | Not needed | All VPS work via terminal SSH |
| **Playwright** | Installed locally | For Stockmock research project only — **not** needed for live API Batman |

**OpenSSH install (confirmed by user):**

```powershell
# Run in Administrator PowerShell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
# Result: Online=True, RestartNeeded=False
```

Verify: `ssh -V` → OpenSSH_10.3p1

---

## Test VPS details (2026-07-10)

| Item | Value |
|------|-------|
| **IP** | `3.110.255.216` |
| **Provider** | AWS Lightsail |
| **Region** | `ap-south-1` (Mumbai) |
| **OS** | Ubuntu 24.04.4 LTS (Noble Numbat) |
| **Hostname** | `ip-172-26-11-146` |
| **SSH user** | `ubuntu` |
| **SSH user that fails** | `root` — Permission denied (publickey) |
| **SSH port** | `22` |
| **RAM** | 3.7 GB |
| **CPU** | 2 cores |
| **Disk** | 77 GB (~68 GB free at test time) |
| **Swap** | None |
| **SSH key (local path)** | `E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem` |
| **Owner** | Friend's server — temporary test only |

**Connect from Windows PowerShell:**

```powershell
ssh -i "E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem" ubuntu@3.110.255.216
```

---

## What we accomplished today

### On local PC (Windows)

| Task | Status |
|------|--------|
| Python 3.12 + pip | OK |
| OpenSSH Client installed (Admin) | OK |
| Git SSH on PATH (fallback) | OK |
| `.ssh` folder created | OK |
| Stockmock deps + Playwright (research project) | OK |
| VPS prerequisites documented | OK |

### On test VPS (friend's Lightsail)

| Task | Status |
|------|--------|
| SSH login as `ubuntu` | OK |
| System packages for Python/browser | OK |
| Dummy Python run on VPS | OK — proved remote execution |
| Uploaded Stockmock project to `~/stockmock-batman-src` | OK (research only; not for live Batman) |
| Python venv + `pip install -r requirements.txt` | OK |
| Playwright Chromium + Linux deps | OK |
| Telegram test via `my_telegram_bot` | **SUCCESS** |
| Agent SSH deploy / run / debug | Confirmed |
| VPS ops deploy (`vps_ops/`) | OK — monitor + fixes |
| All known VPS problems fixed | OK — see [VPS_OPS.md](VPS_OPS.md) |
| 10-iteration stability test | **100% pass rate** |
| `my_telegram_bot` + `vps-monitor` services | Both **active** |
| Test Stockmock folder removed from VPS | Cleaned |

### Dummy Python output (2026-07-10)

```
=== VPS Python Dummy Run ===
Time (UTC): 2026-07-10T13:52:23
Hostname: ip-172-26-11-146
Python: 3.12.3
OS: Linux-6.17.0-1019-aws-x86_64-with-glibc2.39
User: ubuntu
CWD: /home/ubuntu/stockmock-batman-src
2 + 2 = 4
Status: SUCCESS - VPS execution works
```

### Telegram test message

- **Method:** `telegram_notify.send()` from `/home/ubuntu/MA/vps/telegram_notify.py`
- **Credentials:** `/home/ubuntu/my_telegram_bot/.env`
- **Result:** `SEND_RESULT: SUCCESS`
- **Message included:** VPS IP, timestamp, success status

---

## What belongs on VPS for live Batman

When deploying **DEV Batman Algo** to your **own** VPS:

| Component | Notes |
|-----------|-------|
| **Ubuntu 22.04 / 24.04 LTS** | Standard server image |
| **Python 3.10+** | venv in project folder |
| **Broker API client** | JWT / session token; **static IP whitelisted** |
| **Batman signal + order logic** | From this repo — API only |
| **systemd service + timer** | 11:00 IST entry, 15:15 IST exit |
| **Telegram notifications** | Entry, exit, error, daily summary |
| **Log files + rotation** | Avoid unbounded logs |
| **Static IP** | Required for Indian broker APIs |

**Not required for live Batman:**

- Playwright / Chromium / browser
- Stockmock login / UI automation
- More than 4 GB RAM (API-only)

**Suggested deploy path on own VPS:** `~/batman-algo/`

---

## What was already on the test VPS

Friend's existing setup (discovered 2026-07-10):

| Path | Purpose | Status after cleanup |
|------|---------|----------------------|
| `/home/ubuntu/my_telegram_bot/` | Telegram bot (`bot.py`, `notifier.py`, `.env`) | **Fixed** — rotating logs, `.env` token |
| `/etc/systemd/system/my_telegram_bot.service` | Telegram bot systemd unit | **Active** — improved restart policy |
| `/etc/systemd/system/telegrambot.service` | Duplicate bot | **Removed** |
| `/home/ubuntu/vps_ops/` | Monitor, retry, stability test | **Deployed** — see [VPS_OPS.md](VPS_OPS.md) |
| `/etc/systemd/system/vps-monitor.service` | Crash watchdog | **Active** |
| `/home/ubuntu/MA/vps/` | Running MA algo — Breeze API, SQLite | Unchanged |
| `/home/ubuntu/MA/vps/telegram_notify.py` | `send(text)` helper — reuse for Batman | Unchanged |
| `/home/ubuntu/MA/vps/running_ma_vps.py` | Daily orchestrator — **reference pattern** | Unchanged |
| `~/breeze-project/.env` | Breeze API credentials | Unchanged — token refresh still manual |
| `running-ma.timer` | systemd — weekdays ~15:45 IST | Unchanged |
| `~/stockmock-batman-src/` | Test Stockmock upload | **Removed** |

**Copy for Batman:** `running_ma_vps.py` pattern + `vps_ops` monitor layer

---

## Problems and issues found

### SSH / access

| Issue | Detail | Status |
|-------|--------|--------|
| `root@` login fails | Public key denied | Use `ubuntu@` + `sudo` |
| Windows `ssh` not in PATH | OpenSSH not installed | **Fixed** — OpenSSH Client installed 2026-07-10 |
| PowerShell + SSH quoting | `python -c` over SSH breaks | Upload `.py` via `scp`, then run |

### Telegram

| Issue | Detail | Status |
|-------|--------|--------|
| `telegrambot.service` failed | Duplicate bot — `Conflict: getUpdates` | **Fixed** — removed |
| `telegram_bot.log` ~29 MB | Unbounded growth | **Fixed** — truncated + rotation |
| Hardcoded token in `notifier.py` | Security risk | **Fixed** — `.env` only |

### Broker / live trading

| Issue | Detail | Fix |
|-------|--------|-----|
| `BREEZE_SESSION_TOKEN` expires ~24h | Manual browser login to refresh | Automate before unattended Batman runs |
| Static IP required | Broker API whitelist | Lightsail static IP or EC2 Elastic IP |
| Friend's VPS | Not yours long-term | Buy own VPS for production |

### VPS ops fixes applied (2026-07-10 evening)

| Issue | Fix applied | Status |
|-------|-------------|--------|
| Duplicate `telegrambot.service` | Stopped, disabled, masked, unit file removed | **Fixed** |
| 29 MB `telegram_bot.log` | Truncated + RotatingFileHandler + logrotate | **Fixed** |
| Hardcoded token in `notifier.py` | Uses `.env` only | **Fixed** |
| No crash recovery | `vps-monitor.service` + retry with exponential backoff | **Fixed** |
| Test Stockmock deploy | Removed `~/stockmock-batman-src` | **Cleaned** |
| Stability test | 10-iteration kill/recover — **100% pass rate** | **Verified** |

**VPS ops code:** `vps_ops/` → deployed to `/home/ubuntu/vps_ops/`

**Feedback loop:** `state/monitor_state.json`, `logs/monitor.log`, Telegram on crash/recovery

**Stability results:** `state/stability_results.json` — 100% pass, avg recovery ~21s across 10 runs

### Stockmock test deploy (not live Batman)

| Issue | Detail |
|-------|--------|
| Headless `.env` update | Interrupted once; use `HEADLESS=true` on server |
| Playwright on 4 GB VPS | Works but heavy; not needed for API-only Batman |
| Test folder on VPS | **Removed** — was only for connectivity test |

---

## VPS recommendation for production

| Spec | Recommendation |
|------|----------------|
| **Provider** | AWS Lightsail or EC2 |
| **Region** | **ap-south-1 (Mumbai)** |
| **OS** | Ubuntu 22.04 or 24.04 LTS |
| **RAM** | 4 GB (API-only); 8 GB if browser tools also run |
| **CPU** | 2 vCPU |
| **Disk** | 40–80 GB |
| **IP** | **Static** — register with broker |
| **Cost** | ~$20–40/month (Lightsail 4 GB) |

**Ubuntu vs AWS:** Ubuntu is the OS. AWS Mumbai gives static IP + low latency to NSE/brokers. Non-AWS Ubuntu VPS in India also works if static IP is provided.

---

## How the agent connects and manages VPS

| Task | Method |
|------|--------|
| Connect | `ssh -i <key.pem> ubuntu@<IP>` from user's Windows PC |
| Deploy | `scp -r` project to VPS |
| Install | `python3 -m venv .venv`, `pip install -r requirements.txt` |
| Run | systemd timer, cron, `nohup`, or `tmux` |
| Logs | `journalctl`, `tail -f logs/`, project log files |
| Debug | Read logs → patch code → redeploy → restart service |
| Monitor | Telegram alerts + optional health script |
| User involvement | None day-to-day if timers + Telegram configured |

**No Cursor extensions required** — terminal SSH only.

---

## What the agent can and cannot do

### Can do (user stays hands-off)

- Write and fix Batman API code
- Deploy to VPS, install dependencies
- Run tests and live jobs on schedule
- Read logs, debug failures, redeploy fixes
- Send Telegram test and production alerts
- Set up systemd timers, cron, log rotation

### Cannot do without extra setup

| Limit | Why |
|-------|-----|
| 24/7 proactive monitoring | Needs Telegram/cron alerts or user opening Cursor |
| Work when user's PC is off | SSH runs from local PC (VPS jobs still run if systemd set) |
| AWS console (restart, billing) | Needs AWS login |
| Broker OTP / manual login | Needs automation or user once per day until scripted |
| Use friend's VPS forever | Temporary — user must buy own VPS |

---

## SSH commands cheat sheet

```powershell
# Variables
$key = "E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem"
$vps = "ubuntu@3.110.255.216"   # friend's test VPS — replace for production

# Connect
ssh -i $key $vps

# One-liner
ssh -i $key $vps "hostname && python3 --version && free -h"

# Upload DEV Batman Algo (own VPS)
scp -i $key -r "H:\RK Data\Algo Trading Parent\DEV Batman Algo" ubuntu@<YOUR_IP>:~/batman-algo

# On VPS after upload
cd ~/batman-algo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Service checks
sudo systemctl status my_telegram_bot
sudo journalctl -u my_telegram_bot -n 50 --no-pager
```

---

## Telegram integration

| Item | Location (test VPS) |
|------|---------------------|
| Bot credentials | `/home/ubuntu/my_telegram_bot/.env` |
| Env vars | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Send helper (MA) | `/home/ubuntu/MA/vps/telegram_notify.py` → `send(text)` |
| Send helper (ops) | `/home/ubuntu/vps_ops/notifier.py` → `notify(text)` |
| Active services | `my_telegram_bot.service`, `vps-monitor.service` |
| Monitor alerts | Crash, recovery success, recovery failed |

**For DEV Batman Algo:** call `send()` on entry, exit, error; monitor watches systemd units.

```python
import sys
sys.path.insert(0, "/home/ubuntu/MA/vps")
from telegram_notify import send
send("*Batman* Entry placed — NIFTY ...")
```

---

## VPS ops — monitor and stability

Full detail: **[VPS_OPS.md](VPS_OPS.md)**

| Component | Path |
|-----------|------|
| Local source | `H:\RK Data\Algo Trading Parent\DEV Batman Algo\vps_ops\` |
| VPS deploy | `/home/ubuntu/vps_ops/` |
| Watchdog | `service_monitor.py` → `vps-monitor.service` |
| Stability test | `run_stability_test.py` — 10 iterations, 100% pass |
| Feedback state | `state/monitor_state.json` |
| Test results | `state/stability_results.json` |
| Deploy script | `deploy_and_test.sh` |

**Recovery flow:** detect inactive service → exponential backoff retry (5×) → kill stale PID → `systemctl restart` → Telegram alert → update state JSON.

**Typical recovery time:** ~6 seconds (systemd auto-restart); monitor fallback if systemd slow.

---

## Next steps when you get your own VPS

**Automated package (2026-07-17):** see [docs/AWS_ALWAYS_ON_DEPLOY.md](../docs/AWS_ALWAYS_ON_DEPLOY.md) and `vps/`.

1. `bash vps/provision_lightsail.sh` (or create Lightsail Ubuntu 24.04 / 4 GB / Mumbai + static IP in console)
2. `cp vps/deploy.env.example vps/deploy.env` — set `VPS_HOST`, `VPS_SSH_KEY`, `VPS_STATIC_IP`
3. `bash vps/deploy_to_vps.sh` — rsync + systemd `batman-phase1.target` in **UAT** mode
4. `bash vps/smoke_live_ticks.sh --remote`
5. After several good sessions: whitelist static IP with Dhan → `bash vps/prod_cutover_checklist.sh --apply-prod`
6. Keep JWT refresh operational (DRISHTI / morning operator step until automated)

---

## Session log — 2026-07-10

| Time (IST) | Action |
|------------|--------|
| ~19:00 | Discussed VPS prerequisites; local Python/Playwright setup |
| ~19:05 | User asked about agent managing VPS hands-off |
| ~19:10 | Installed local deps; Git SSH added to PATH |
| ~19:16 | First SSH to `3.110.255.216` as `ubuntu` — success |
| ~19:18 | Uploaded Stockmock test project; venv + Playwright on VPS |
| ~19:22 | Dummy Python on VPS — success |
| ~19:28 | Found `my_telegram_bot`, `MA/vps` on friend's server |
| ~19:30 | Telegram test — **SUCCESS** |
| ~21:00 | Clarified: live Batman = broker API only; Stockmock = research |
| ~21:04 | VPS spec discussion — Ubuntu on AWS Mumbai, 4 GB, static IP |
| ~21:07 | Created context docs in DEV Batman Algo |
| ~21:22 | User installed OpenSSH Client (Admin PowerShell) — confirmed |
| ~21:24 | Context files updated |
| ~21:35 | User asked to fix all VPS problems + retry/monitor + stability test |
| ~21:42 | VPS ops deployed — cleanup, monitor, 10-iteration test (100% pass) |
| ~21:53 | User asked problems explained (Telegram duplicate, Breeze token, etc.) |
| ~23:53 | All context files updated with full session + VPS ops docs |

---

## Resume later — AWS always-on (parked 2026-07-17 / 18 night IST)

**Status:** Package built in-repo; **Lightsail not purchased yet** (no AWS CLI creds on this machine). Bots stopped on laptop for the night.

**Already done**
- Systemd + deploy package: `vps/` + [docs/AWS_ALWAYS_ON_DEPLOY.md](../docs/AWS_ALWAYS_ON_DEPLOY.md)
- Units: `batman-drishti` / `batman-kavach2` / `batman-jagran` / `batman-saransh` + `batman-phase1.target` + `vps-monitor-batman`
- Scripts: `provision_lightsail.sh`, `deploy_to_vps.sh`, `install_systemd.sh`, `smoke_live_ticks.sh`, `prod_cutover_checklist.sh`
- Local smoke PASS (UAT); Stage A = UAT shadow on VPS, Stage B = prod after Dhan IP whitelist

**Operator next (when continuing)**
1. Create Lightsail Mumbai Ubuntu 24.04, **4 GB RAM / 2 vCPU**, **40–80 GB** disk, **static IP**, download `.pem`
2. `cp vps/deploy.env.example vps/deploy.env` → set `VPS_HOST`, `VPS_SSH_KEY`, `VPS_STATIC_IP`
3. `bash vps/deploy_to_vps.sh` then `bash vps/smoke_live_ticks.sh --remote`
4. Later: Dhan whitelist → `bash vps/prod_cutover_checklist.sh --apply-prod`

### Sizing (measured on this DEV box 2026-07-17)

| Resource | Recommendation | Notes |
|----------|----------------|-------|
| **RAM** | **4 GB** | Four Phase-1 bots ~550–650 MB RSS; leave headroom. 2 GB is tight. |
| **CPU** | **2 vCPU** | Enough for API + Telegram polling |
| **Disk** | **40 GB** (80 GB if long log history) | Not a web server — SSH only |

**Live RSS snapshot (all five including legacy KAVACH):** ~670 MB total (DRISHTI ~117, KAVACH2 ~234, JAGRAN ~103, SARANSH ~104, KAVACH ~112).

### What eats disk (largest first)

| Consumer | Size / growth | VPS tip |
|----------|---------------|---------|
| `logs_runtime/` | **~50 MB/day** (~20 MB DRISHTI); grows forever | Keep 7–14 days; archive/delete older |
| `.venv/` | **~360–410 MB** one-time | Required; pandas/numpy dominate |
| `backtest_engine/cache/api-scrip-master-detailed_*.csv` | **~35–40 MB each** (duplicated under `kavach-2.0/`) | Keep latest only on VPS |
| `Dependencies/all_instrument *.csv` | **~27 MB each** | Trim old dumps |
| `security_id_list.csv` | **~29 MB** | One file |
| `data_runtime/` | **~10 MB** now | Slow growth (ledgers/state) |
| Nifty `ws_ltp_YYYYMMDD.log` | **~2 MB/day** | Small vs full bot log volume |

**Do not** treat friend’s Lightsail `3.110.255.216` as permanent prod.

---

## Related paths

| Path | Role |
|------|------|
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo` | **Main project** — live API Batman |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\context\` | Context docs |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\context\VPS_OPS.md` | Monitor, retry, stability, deploy |
| `H:\RK Data\Algo Trading Parent\DEV Batman Algo\vps_ops\` | Ops code (local) |
| `H:\RK Data\Algo Trading Parent\Stockmock 11.00 PM vs 3.15 PM Batman Deployment` | Research scraper only |
| `E:\DOWNLOADS\Chrome Downloads\LightsailDefaultKey-ap-south-1.pem` | Friend's test VPS SSH key |
| `/home/ubuntu/vps_ops/` | Ops code (on test VPS) |

---

*Update when you get your own VPS, change broker, or complete Batman API deployment.*
