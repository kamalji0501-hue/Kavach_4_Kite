# July 23 Excel backtest — SUCCESS (2026-07-28)

Operator locked this as the **working reference** for UAT backtesting.  
VPS snapshot: `/home/ubuntu/backups/backtest_success_20260728_20260728_180551`

---

## Verdict

End-to-end UAT on VPS (`13.126.134.192`) with DRISHTI replaying **2026-07-23** 1-minute Excel bars at **3x** was a **SUCCESS**:

- KAVACH 2.0 ATO TRIGGERED / EXITED
- **30% Dynamic Hedge EXITED** (once per side per day)
- SARANSH ATO Cycle Buy / Sell / Impact from historical option premiums (not `5.00` fallback)

At close: **DRISHTI UAT replay OFF** (`enabled=false`, `force_uat_mode=false`) → LIVE mode.  
`batman_mode` remains **uat**. Replay source logs + 8-leg book kept on disk.

---

## How it ran (do not regress)

| Piece | Working setting |
|--------|------------------|
| Host | `ubuntu@13.126.134.192` · PEM `Server_connect/Algo_test.pem` · `/home/ubuntu/batman-algo` |
| Mode | `uat` |
| Replay source Excel | `…/Fetch Historical Data/…/4_42_PM_24050CE_24200CE_23800PE_23650PE_1m.xlsx` |
| NIFTY ticks | `…/2026-07-23/drishti/logs/nifty_rest_ltp/rest_ltp_20260723.log` (375 bars) |
| Option premiums | `…/option_ltp/option_ltp_20260723.log` (strike keys + `ce_protect`/`pe_protect`) |
| Replay params (when ON) | `enabled=true`, `force_uat_mode=true`, `replay_speed=fast` (**3x**), `session_tail_hours=0`, `max_source_days=1`, `loop=true` |
| Book | Sensibull **28 Jul 2026** 8-leg `cursor_chat` → `Trading_Runtime/Data/data/uat/deployed_positions/positions.json` |
| Dyn hedge | Register persists `pe_dyn_hedge` / `ce_dyn_hedge`; **`exit_enabled` auto-True** on confirm |

### Excel → log mapping (ATO protect)

| Excel sheet | Log roles |
|-------------|-----------|
| `24050_CE` | `ce_protect`, `ce_24050`, `ce_sell` |
| `23800_PE` | `pe_protect`, `pe_23800`, `pe_sell` |
| `24200_CE` | `ce_24200`, `ce_buy` (30% dyn hedge) |
| `23650_PE` | `pe_23650`, `pe_buy` (30% dyn hedge) |

---

## Bugfixes that must stay in both trees (root + `kavach-2.0/`)

1. **`kavach-2.0/core/nifty_ltp_feed.py`** — `read_nifty_ltp_cache` must parse **`replay_market_time`**. Dropping it caused shadow fills → UAT fallback **5.00** → SARANSH Buy=Sell Impact=0.
2. **`core/option_ltp_uat_lookup.py`** — strike-specific keys (`ce_24050` / `pe_23800`) before role `*_protect`.
3. **`kavach-2.0/bat_telegram/bots/kavach2/bot.py`** — on Register confirm, set `dyn_hedge.exit_enabled=True` when dyn legs exist; clear `*_exited_date`.
4. **`modules/ato_protection.py`** — INFO logs for dyn-hedge skips; ledger premium prefers replay option_ltp over fill/fallback.
5. **`backtest_engine/shadow/order_ledger.py`** — warn when `uat_replay` active but option_ltp miss.

Sha256 of VPS copies at success: see snapshot `code_markers/sha256_fixed_modules.txt`.

---

## Re-run the same backtest

1. Ensure replay logs under  
   `Trading_Runtime/Logs/uat/runtime/2026-07/2026-07-23/drishti/logs/{nifty_rest_ltp,option_ltp}/`  
   (or restore from snapshot `replay_logs/`).
2. `telegram/bots/drishti/params.json` → turn **ON** the recipe in the table above.
3. Restart `batman-drishti` → confirm log: `Mode selected = UAT_REPLAY`.
4. FAST UAT book if needed → **Register** in KAVACH 2.0 (dyn hedge arms automatically).
5. Watch SARANSH ATO Cycle + KAVACH 🛡 30% Dynamic Hedge EXITED on first ATO per side.

---

## Close state (2026-07-28 ~18:06 UTC)

| Item | State |
|------|--------|
| DRISHTI | **LIVE** (`uat_market_replay.enabled=false`) |
| KAVACH2 / SARANSH / JAGRAN | left running (UAT mode) |
| Replay recipe | frozen in VPS backup + this file |
| Next | Market/live ops or next backtest day — do **not** leave force_uat_mode on overnight unless intentional |
