# Drishti always-on + on-time JWT (rahul_Changes)

**Date:** 2026-08-09

## Uptime
- systemd unit: `batman-drishti.service`
- WorkingDirectory / ExecStart: `/home/ubuntu/rahul_Changes`
- `Restart=always`, `RestartSec=5`
- Enabled for `multi-user.target` (survives reboot)

## JWT on time
1. **In-process** `TotpRenewer` in `run_drishti.py` — poll 300s, renew when ≤4h left.
2. **Cron every 5 min:** `/etc/cron.d/batman-drishti-ensure` → `vps/ensure_drishti.sh`
   - restarts unit if down
   - renews JWT when ≤6h left (forces auto_renew ON)
   - restarts Drishti after renew so broker hot-loads

## Secrets
`/home/ubuntu/Trading_Runtime_Rahul/Credentials/config/.env` (+ `dhan.env`)

## Checks
```bash
systemctl is-active batman-drishti.service
journalctl -u batman-drishti -n 50 --no-pager
tail -50 /home/ubuntu/Trading_Runtime_Rahul/Logs/uat/runtime/ops/ensure_drishti.log
cat /home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/drishti_ensure_state.json
```

GO remains on batman-algo / Trading_Runtime (independent).
