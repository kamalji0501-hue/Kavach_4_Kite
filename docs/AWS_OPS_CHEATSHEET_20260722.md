# Batman VPS Ops Cheatsheet

SSH: `ssh -i BMAlgo.pem ubuntu@3.110.43.9`  
Root: `/home/ubuntu/batman-algo`  
Mode: `uat`

```bash
sudo systemctl start|stop|restart|status batman-phase1.target
systemctl is-active batman-drishti batman-kavach2 batman-jagran batman-saransh
journalctl -u batman-drishti -n 100 --no-pager
.venv/bin/python scripts/bot_status.py all
```

Rollback archive: `/home/ubuntu/backups/batman-algo_pre_deploy_20260722_062118.tar.gz`
