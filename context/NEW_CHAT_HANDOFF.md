# Context bridge — Kamalji ownership (2026-08-06)

**Read first:** [`KAMALJI_HANDOFF.md`](KAMALJI_HANDOFF.md) and [`CURSOR_AI_GUIDE_FOR_KAMALJI.md`](CURSOR_AI_GUIDE_FOR_KAMALJI.md).

Rahul finished restructuring. This file’s older July backtest notes remain below for history only.

---

# New Chat Handoff — resume after 2026-07-28 (July-23 Excel backtest SUCCESS)

**Purpose:** Read this file **first** in the next Cursor chat.  
**Operator:** Rahul / Kamal — backtesting closed **2026-07-28 ~18:06 UTC / ~23:36 IST**.  
**Machine (local):** Chromebook · Debian 13 · Python 3.13 · Linux.  
**Workspace root:**  
`/home/kamalji0501e/Batman Algo Files/15 July 26 DEV Batman Algo/DEV Batman Algo`  
**VPS (live):** `ubuntu@13.126.134.192` · `/home/ubuntu/batman-algo` · PEM  
`/home/kamalji0501e/Batman Algo Files/Server_connect/Algo_test.pem`  
*(Old IPs `3.110.43.9` / friend Lightsail are obsolete for this deploy.)*

**Canonical success doc:** [`context/BACKTEST_JUL23_SUCCESS.md`](context/BACKTEST_JUL23_SUCCESS.md)  
**VPS snapshot:** `/home/ubuntu/backups/backtest_success_20260728_20260728_180551`

---

## End state (locked at close)

| Item | State |
|------|--------|
| VPS Phase 1 | **RUNNING** (DRISHTI / KAVACH2 / JAGRAN / SARANSH) |
| VPS mode | **uat** |
| DRISHTI UAT replay | **OFF** — `enabled=false`, `force_uat_mode=false` → **LIVE** feed |
| July-23 replay logs | **Kept** on VPS under `Trading_Runtime/Logs/.../2026-07-23/drishti/logs/` + snapshot |
| UAT book | Sensibull **28 Jul 2026** 8-leg `cursor_chat` (still on VPS) |
| Dyn hedge | `exit_enabled` auto-on at Register when dyn legs exist (**shipped**) |
| SARANSH premiums | Replay `option_ltp` @ `replay_market_time` (**shipped** — do not drop cache field) |
| Local params | Replay **OFF** (mirrors VPS) |
| **Next focus** | Live/market ops, or re-run backtest per `BACKTEST_JUL23_SUCCESS.md` |

---

## This session shipped (keep working)

1. **July 23 Excel → Drishti replay @ 3x** on VPS for KAVACH 2.0 UAT  
2. **FAST UAT** 8-leg Sensibull book (28 Jul 2026)  
3. **Fix:** `kavach-2.0` cache reader dropped `replay_market_time` → Buy=Sell=5.00 — **fixed**  
4. **Fix:** 30% dyn hedge silent skip when `exit_enabled=False` — **auto-enable on Register** + INFO skip logs  
5. **Fix:** strike-specific option_ltp keys from Excel (24050 CE / 23800 PE protect)  
6. Operator confirmed **Backtesting was a SUCCESS**

---

## Resume checklist

1. Read `context/BACKTEST_JUL23_SUCCESS.md`  
2. SSH: `ssh -i "…/Server_connect/Algo_test.pem" ubuntu@13.126.134.192`  
3. Status: `systemctl is-active batman-drishti batman-kavach2 batman-jagran batman-saransh`  
4. To **re-run same backtest:** follow restore steps in success doc (do **not** leave `force_uat_mode=true` overnight unless intentional)  
5. Do **not** regress the five bugfix files listed in the success doc (root + `kavach-2.0/` must stay in sync)

---

## Do not

- Treat friend’s Lightsail / `3.110.43.9` as current VPS  
- Re-enable UAT replay without restoring July-23 `option_ltp` log (SARANSH will show 5.00 again)  
- Ship `kavach-2.0/core/nifty_ltp_feed.py` without `replay_market_time` in `read_nifty_ltp_cache`
