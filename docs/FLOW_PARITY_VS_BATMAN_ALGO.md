# Flow parity: `rahul_Changes` vs OLD `/home/ubuntu/batman-algo`

Audit date: 2026-08-06 (Rahul restructuring + Place Order / Paper-Live).

## Verdict

**ATO breach / protect / exit conditions match OLD.**  
Intentional differences only: Paper/Live, OrderManager backend Place Order, money audit / log prefixes, runtime secrets layout, optional PIN/TOTP.

## Compared trees

| Role | Path |
|------|------|
| OLD (Kamalji tested) | `/home/ubuntu/batman-algo` (+ `kavach-2.0/`) |
| NEW (Rahul) | `/home/ubuntu/rahul_Changes` (+ `kavach-2.0/`) |

## ATO / Kavach2 conditions

Normalized method parity on `ATOProtection` (OLD `modules/ato_protection.py` ≡ OLD `kavach-2.0/...`, vs NEW `kavach-2.0/modules/ato_protection.py`):

| Method | Result |
|--------|--------|
| `_check_breach` | MATCH |
| `_execute_protect_buy` | MATCH |
| `_exit_ce_ato` / `_exit_pe_ato` | MATCH |
| `_place_ce_protection` / `_place_pe_protection` | MATCH |
| `_mark_awaiting_clearance_after_exit` | MATCH |
| All other ATOProtection methods (except place) | MATCH |
| `_place_ato_aggressive_limit` | **Intentional DIFF** — NEW routes paper via `order_manager.punch_ato` / BackendOrderWorkflow; live clears OM and uses legacy `broker.place_aggressive_limit` |

Header rules unchanged: CE/PE touch sell-strike → BUY protect; retrace → SELL exit.

Operator keys used in breach path (`limit_buffer_pct`, soft-cap flags, chase timeouts, tick size) — same set as OLD.

## Identical / unchanged vs OLD (Kavach2)

| File | Note |
|------|------|
| `kavach-2.0/bat_telegram/bots/kavach2/bot.py` (pre-Paper port) | Was byte-identical on `wizard_entry` body vs OLD before Paper step |
| `kavach-2.0/bat_telegram/bots/kavach2/register_wizard.py` | Was hash-identical to OLD; Paper state/handler added |
| `kavach-2.0/core/state.py` | Same hash |
| `kavach-2.0/core/wizard_plan.py` | Was same hash; `order_mode` leading step added |
| `BatmanBroker.place_aggressive_limit` / `place_order` / cancel / LTP / positions | Normalized MATCH; NEW only adds `connect_with_pin_totp` |

## Intentional differences (keep)

1. **Paper / Live** — first `/register` question; persisted as `order_mode` on deployment JSON + state.
2. **Order sink** — `run_kavach2.py` → `configure_ato_order_sink` (paper OM / live broker).
3. **Place Order backend** — ATO punches via backend workflow (no Telegram Place Order UI).
4. **Logging** — `[PAPER TRADE]` / `[LIVE TRADE]` prefixes; money audit JSONL.
5. **Runtime** — `Trading_Runtime_Rahul` + `Credentials/` secrets_root (not in git).
6. **PIN/TOTP** — optional capability for token refresh / historical.

## Gaps found and fixed (this pass)

1. **Phase-1 Kavach2 lacked Paper/Live on register** while root Kavach had it and `run_kavach2` defaulted order sink without a wizard choice.  
   **Fixed:** Ported Paper/Live into:
   - `kavach-2.0/core/wizard_plan.py`
   - `kavach-2.0/bat_telegram/bots/kavach2/register_wizard.py`
   - `kavach-2.0/bat_telegram/bots/kavach2/bot.py` (`wizard_entry` → mode UI → `_wizard_continue_after_order_mode` → same UAT/fetch as OLD)
   - deployment write now stores `order_mode`
2. **Root Kavach `_wizard_continue_after_order_mode`** could `NameError` on UAT (`broker` / `is_uat` / `workspace_root` not bound). **Fixed.**

## Verification run

- ATO method mismatch count (excl. intentional place): **0**
- `scripts/verify_ato_backend_no_telegram.py`: **5/5 GREEN**
- `scripts/robot_verify_phase1.py`: **ALL CHECKS PASSED**
- Import smoke: wizard plan starts with `order_mode`; ATOProtection imports OK

## What operators should still do

- On `/register` (Kavach2): pick **Paper** or **Live** first; remaining questions match Kamalji-tested flow.
- Live money: choose **Live trade** (or `ORDER_MODE=live`); paper never hits exchange.
- Do not mix Rahul runtime with Kamalji `Trading_Runtime` / `batman-algo` systemd.
