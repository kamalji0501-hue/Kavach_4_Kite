# Evidence checklist for testers (Rahul track)

Runtime root: `/home/ubuntu/Trading_Runtime_Rahul`  
Code under test: `/home/ubuntu/rahul_Changes`  
Baselines (read-only help): `/home/ubuntu/batman-algo`, `/home/ubuntu/place-order-bot`

## After every run, confirm

| Step | What to see | Where |
|------|-------------|-------|
| Bot start | `logging.bootstrap.evidence`, `audit.configure` | `Logs/uat/.../{bot}/audit/money_audit.jsonl` |
| Register mode | `register.order_mode` / `register.order_mode.ui` | same |
| Confirm | `register.confirm.evidence`, `deployment.sync.evidence`, `order_mode.sink.detail` | same |
| ATO punch paper | `ato.order_sink.decision` via=order_manager, `order_manager.punch_ato.*`, `backend.punch.*`, `paper_book.fill` | same + `Data/.../paper_position_book.json` |
| ATO punch live | `ato.order_sink.decision` via=legacy_broker, broker place logs | audit + bot `all.log` |
| Ticks | CSV rows with nifty + CE/PE | `Data/.../ato_tick_csv/` |

## Robot command

```bash
cd /home/ubuntu/rahul_Changes
.venv/bin/python scripts/run_five_scenario_hardening.py
```

Expect 5/5 scenarios × N cycles green.
