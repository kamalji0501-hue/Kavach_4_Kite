# Detailed money logging (2026-08-06)

Real-money ops need a full trail of what every bot / ATO / OrderManager did.

## Where logs live

Runtime root (Rahul): `Trading_Runtime_Rahul/Logs/<mode>/YYYY-MM/YYYY-MM-DD/`

Per bot:

- `{bot}/logs/all.log` — human tail (now **DEBUG** when enabled)
- `{bot}/logs/{module}_{window}.log` — windowed runtime
- `{bot}/errors/all_errors.log`
- `{bot}/audit/money_audit.jsonl` — **structured money events** (orders, ATO, TG control)
- `{bot}/audit/detail_debug.jsonl` — DEBUG+ from trading namespaces (JSONL)

## Config (`config/settings.json` → `logging`)

```json
{
  "enabled": true,
  "level": "DEBUG",
  "audit_jsonl": true,
  "detail_jsonl": true,
  "debug_trading": true
}
```

## Secrets

`core/money_audit.redact` strips tokens, JWTs, TOTP, passwords, Authorization headers.
Never commit audit files; they stay under Trading_Runtime_*.

## Key events

| event | meaning |
|-------|---------|
| `audit.configure` | bot logging + audit armed |
| `telegram.command` / `.callback` / `.message` | every inbound TG update |
| `ato.place_aggressive.*` | ATO protect punch path |
| `order_manager.punch_ato.*` | OrderManager → Place Order backend |
| `backend.punch.*` | Place Order `BackendOrderWorkflow.punch` |

## Verify

```bash
cd /home/ubuntu/rahul_Changes
.venv/bin/pytest tests/test_money_audit.py tests/test_backend_workflow.py -q
tail -f $(.venv/bin/python -c "from pathlib import Path; from core.money_audit import audit_paths; print(audit_paths(Path('.'),'kavach')[0])")
```
