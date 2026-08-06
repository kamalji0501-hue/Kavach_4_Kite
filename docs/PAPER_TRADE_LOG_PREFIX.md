# Paper / Live trade log prefixes

When order mode is **paper**, human logs are prefixed with:

```text
[PAPER TRADE]
```

When **live**:

```text
[LIVE TRADE]
```

## Implementation

- `core/paper_trade_logging.py` — ContextVar + `TradeLaneFormatter`
- Wired in `core/bot_logging.py`
- `money_audit` stamps `trade_lane` and mirrors paper events to `money_audit_paper.jsonl`
- Set automatically by `configure_ato_order_sink` / OrderManager punch

## Verify

```bash
.venv/bin/python scripts/run_ten_paper_ft_cases.py
# expect ALL_TEN_PAPER_FT_GREEN and log_has_paper_prefix=true
```

Paper punches never hit the exchange (FakeBroker / BackendOrderWorkflow.for_paper).
