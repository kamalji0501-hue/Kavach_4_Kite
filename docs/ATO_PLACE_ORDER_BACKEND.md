# ATO → Place Order backend (no Telegram bot)

## Product rule

Place Order Telegram bot was built to **test slippage / chase**. In the master product:

- There is **no** Place Order bot in the user flow
- **No** slippage buttons / questions
- When ATO **engages** (NIFTY breaches sell range) → backend punches **BUY** protect
- When ATO **exits** (back in range) → backend punches **SELL**
- Slippage uses **premium_table** bands inside Place Order `ExecutionEngine`

## Code path (Kavach2 / Phase-1)

```text
ATOProtection._place_ato_aggressive_limit
  → if order_manager attached (paper):
        OrderManager.punch_ato
          → BackendOrderWorkflow.punch  (FakeBroker paper)
          → ExecutionEngine + SlippageTable(premium_table)
  → else (live):
        broker.place_aggressive_limit  (existing live path)
```

Paper sink is attached by `configure_ato_order_sink(..., order_mode="paper")` at Kavach2 start.

## Verify

```bash
.venv/bin/python scripts/verify_ato_backend_no_telegram.py
# expect ATO_BACKEND_VERIFY_GREEN (5 buy+sell cycles)
```
