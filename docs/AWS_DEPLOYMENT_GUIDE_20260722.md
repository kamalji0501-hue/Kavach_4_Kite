# Batman Algo — AWS Ubuntu 24.04 Deployment Guide

**Deployed:** 2026-07-22  
**Host:** 3.110.43.9 (`ip-172-31-13-155`)  
**SSH user:** `ubuntu` (PEM: `BMAlgo.pem`)  
**Install path:** `/home/ubuntu/batman-algo`  
**Mode:** `uat` (ShadowBroker — no live orders)  
**Pre-deploy backup:** `/home/ubuntu/backups/batman-algo_pre_deploy_20260722_062118.tar.gz`

## Architecture overview

| Component | Role |
|-----------|------|
| `batman-drishti.service` | Nifty LTP feed + Telegram |
| `batman-kavach2.service` | ATO protection |
| `batman-jagran.service` | Alerts |
| `batman-saransh.service` | Reporting / PnL |
| `batman-phase1.target` | Groups all four robots |
| `vps-monitor-batman.service` | Crash watchdog |
| CloudWatch Agent | CPU/RAM/Disk/Net metrics |
| Health cron | `batman_health_check.sh` every 5 min |

## Startup

```bash
ssh -i BMAlgo.pem ubuntu@3.110.43.9
sudo systemctl start batman-phase1.target
sudo systemctl start vps-monitor-batman.service
systemctl is-active batman-drishti batman-kavach2 batman-jagran batman-saransh
cd /home/ubuntu/batman-algo && .venv/bin/python scripts/bot_status.py all
```

## Restart

```bash
sudo systemctl restart batman-phase1.target
# or single:
sudo systemctl restart batman-drishti.service
```

## Stop

```bash
sudo systemctl stop batman-drishti batman-kavach2 batman-jagran batman-saransh batman-phase1.target
```

## Monitoring

```bash
htop
/home/ubuntu/batman-ops/bin/batman_health_check.sh
journalctl -u batman-drishti -f
sudo systemctl status amazon-cloudwatch-agent
```

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Bot not running | `systemctl status batman-<name>`; `journalctl -u batman-<name> -n 100` |
| Telegram fail | `telegram/bots/*/token.env` |
| LTP stale / ATO pause | Off-hours or DRISHTI not feeding yet |
| Dhan token expired | Refresh via DRISHTI; UAT uses ShadowBroker |
| Low RAM | Instance has 1.9 GiB — recommend ≥4 GiB for prod |
| SSH denied | User must be `ubuntu` + PEM key |

## Backup

```bash
TS=$(date +%Y%m%d_%H%M%S)
tar -C /home/ubuntu -czf /home/ubuntu/backups/batman-algo_${TS}.tar.gz batman-algo
```

## Disaster recovery / rollback

```bash
sudo systemctl stop batman-phase1.target vps-monitor-batman.service
tar -C /home/ubuntu -xzf /home/ubuntu/backups/batman-algo_pre_deploy_20260722_062118.tar.gz
cd /home/ubuntu/batman-algo
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo systemctl start batman-phase1.target
```

## Security

- UFW: SSH only inbound
- Fail2Ban: sshd jail
- SSH: pubkey only, root disabled, AllowUsers ubuntu
- Secrets: chmod 600

## Prod cutover

**Not applied.** Keep `uat` until Dhan whitelists `3.110.43.9` and you explicitly approve prod.

## Local-only: PNL Summary bot

The standalone **PNL Summary** project (`Batman Algo Files/PNL summary` — Zerodha Kite → Telegram) must **never** be copied to this server. It is not part of Batman Phase-1 systemd. Deploy scripts block and exclude it (`vps/rsync-excludes.txt`, `vps/deploy_to_vps.sh`).

## DRISHTI after 15:30 IST (VPS only)

On this AWS host, **DRISHTI must not run off-hours UAT replay** after market close.

- Cron (IST): **15:30 Mon–Fri** → `drishti_vps_after_close.sh` stops `batman-drishti.service` and locks `uat_market_replay.enabled=false`
- Cron (IST): **09:00 Mon–Fri** → `drishti_vps_premarket_start.sh` starts DRISHTI again
- Install/reinstall: `bash vps/install_drishti_vps_schedule.sh`
- KAVACH2 / JAGRAN / SARANSH are **not** stopped by this policy
