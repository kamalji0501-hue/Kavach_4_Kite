# AWS always-on deploy (Stage A UAT → Stage B PROD)

Operator runbook for the plan in Cursor: **AWS Always-On Deploy**.

## Architecture

Four systemd services under `batman-phase1.target`:

| Unit | Runner |
|------|--------|
| `batman-drishti.service` | `run_drishti.py` |
| `batman-kavach2.service` | `run_kavach2.py` (After DRISHTI) |
| `batman-jagran.service` | `run_jagran.py` |
| `batman-saransh.service` | `run_saransh.py` |

Crash watchdog: `vps-monitor-batman.service` → watches the four units (see `vps_ops/service_monitor.py`).

**Stage A:** mode=`uat` — live Nifty WS ticks, **shadow** orders.  
**Stage B:** mode=`prod` — after Dhan static-IP whitelist — live orders.

## Quick path

```bash
# 0) Create / attach Lightsail (Mumbai, 4 GB) — needs AWS CLI creds OR console
bash vps/provision_lightsail.sh

# 1) Configure SSH target
cp vps/deploy.env.example vps/deploy.env
# edit VPS_HOST, VPS_SSH_KEY, VPS_STATIC_IP

# 2) Validate units locally (no install)
bash vps/install_systemd.sh --dry-run

# 3) Deploy code + enable systemd on VPS (UAT)
bash vps/deploy_to_vps.sh

# 4) Smoke
bash vps/smoke_live_ticks.sh --remote

# 5) Later — prod cutover
bash vps/prod_cutover_checklist.sh
# after Dhan whitelist:
bash vps/prod_cutover_checklist.sh --apply-prod
```

## Specs (locked)

| Item | Value |
|------|--------|
| Region | `ap-south-1` Mumbai |
| OS | Ubuntu 24.04 |
| Size | ~2 vCPU / 4 GB (`medium_3_0` Lightsail bundle) |
| Path on VPS | `/home/ubuntu/batman-algo` |
| Static IP | Required for Stage B Dhan whitelist |

## Files

| Path | Role |
|------|------|
| `vps/systemd/*.service` | Unit templates (`__BATMAN_ROOT__` placeholders) |
| `vps/install_systemd.sh` | Render + install units |
| `vps/deploy_to_vps.sh` | rsync + remote bootstrap |
| `vps/provision_lightsail.sh` | AWS Lightsail create + static IP |
| `vps/deploy.env.example` | Env template (copy to `deploy.env`) |
| `scripts/vps_smoke_live_ticks.py` | Bot + tick-log smoke |
| `vps/prod_cutover_checklist.sh` | Stage B checklist / apply |

## Do not

- Use the friend’s Lightsail (`3.110.255.216`) as permanent prod
- Commit `vps/deploy.env` or secrets
- Flip to `prod` before Dhan whitelists the static IP
- **Ship the local `PNL summary` bot (Zerodha/Kite Telegram bot) to any VPS** — that project stays on the laptop only (`Batman Algo Files/PNL summary`). Deploy refuses if its fingerprints appear under the Batman repo root; see `vps/rsync-excludes.txt`.
