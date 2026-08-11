# Kavach2 always-on (rahul_Changes)

**Date:** 2026-08-09

- systemd: `batman-kavach2.service` → `/home/ubuntu/rahul_Changes/run_kavach2.py`
- `Restart=always`, enabled at boot
- Cron every 5m: `vps/ensure_kavach2.sh`
- Starts after Drishti when possible (`After=batman-drishti.service`)
- JWT remains Drishti’s responsibility (`docs/DRISHTI_ALWAYS_ON.md`)

```bash
systemctl is-active batman-kavach2.service
journalctl -u batman-kavach2 -n 50 --no-pager
tail -50 /home/ubuntu/Trading_Runtime_Rahul/Logs/uat/runtime/ops/ensure_kavach2.log
```
