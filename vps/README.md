# VPS / AWS package

Always-on deploy for Phase-1 bots. See **[docs/AWS_ALWAYS_ON_DEPLOY.md](../docs/AWS_ALWAYS_ON_DEPLOY.md)**.

**Local-only (never ship):** the sibling project `Batman Algo Files/PNL summary` (Zerodha Kite PNL Telegram bot). Excluded via `rsync-excludes.txt` and refused by `deploy_to_vps.sh` if present under the Batman tree.

```bash
bash vps/provision_lightsail.sh      # create Lightsail or print console steps
bash vps/install_systemd.sh --dry-run
bash vps/deploy_to_vps.sh            # needs vps/deploy.env
bash vps/smoke_live_ticks.sh
bash vps/prod_cutover_checklist.sh
```

Status files written by scripts (local, gitignored patterns):

- `lightsail.STATUS`
- `smoke_last_report.json`
- `prod_cutover.STATUS`
