# Paper vs Live on Kavach /register

## Behaviour

1. `/register` first question: **Paper trade** or **Live trade**.
2. Rest of the wizard is unchanged.
3. Deployment JSON includes `"order_mode": "paper"|"live"`.
4. **Paper:** ATO punches via `OrderManager` → Place Order paper FakeBroker → `paper_position_book.json`. Exchange is never hit.
5. **Live:** `OrderManager` is cleared; ATO uses the existing broker `place_aggressive_limit` path (same as pre-OM production).

## Override

Env `ORDER_MODE=paper|live` overrides deployment at Kavach process start.

## Tests

`pytest tests/test_order_mode_register.py tests/test_wizard_plan.py -q`
