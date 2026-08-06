# GO — Independent Bot Context

**Resume from here.** Last saved: **2026-08-01 ~09:55 IST**  
**Status:** Implemented + **running on VPS** (KAVACH-style alive card)  
**Scope:** Independent Telegram robot — does **not** start/stop with Phase 1  
**Broker:** Dhan via shared JWT (`TokenStore` + `create_broker`); mock/live gates respected  

---

## Current runtime (as of save)

| Item | Value |
|------|--------|
| Telegram bot | [@GO_batman_bot](https://t.me/GO_batman_bot) |
| Chat ID | `5143751536` (Kamal private) |
| Secrets | `GO/telegram/bots/go/token.env` + VPS `Trading_Runtime/Credentials/telegram/bots/go/token.env` |
| **Primary host** | **VPS** `batman-go.service` (`/home/ubuntu/batman-algo`) |
| Batman mode on VPS | **uat** (ShadowBroker / virtual orders) |
| Phase 1 | Untouched — GO is `WantedBy=multi-user.target` only |
| UI | Logo alive card + GO-only buttons |

**VPS ops**

```bash
sudo systemctl status batman-go.service
sudo systemctl restart batman-go.service
sudo systemctl stop batman-go.service
sudo journalctl -u batman-go.service -f
```

Deploy wiring: `vps/systemd/batman-go.service`, `vps/install_systemd.sh` (INDEPENDENT_UNITS), `vps/deploy_to_vps.sh` (token loop includes `go`).

**Laptop:** do **not** run local `run_go.py` while VPS GO is up (Telegram 409 Conflict). Local start/stop scripts remain for offline work only.

---

## Purpose (locked)

Operator-driven NIFTY option trading:

1. **Multi-leg (Batman 2.0)** — enter all **8** legs from an operator NIFTY level. **Entry only** (no exit in GO).
2. **Single-leg** — Buy CE or Buy PE with fixed SL + Target at entry, then trailing SL/Target, plus operator **Exit**.

Signal source: **manual Telegram taps only** (no webhook / external feed).

---

## Layout (all GO code under `GO/`)

```
GO/
  bot.py                         # Alive card UI + wizards
  book.py                        # GO-owned position book (JSON)
  GO_CONTEXT.md                  # this file — resume handoff
  README.md
  strategy/
    __init__.py
    batman2_legs.py              # L → 8-leg plan (pure, unit-tested)
    multileg_entry.py            # sequential Dhan entry
    single_leg.py                # entry + SL/target/trail monitor + exit
  telegram/bots/go/
    params.json
    token.env.example
    token.env                    # GO_BOT_TOKEN + GO_CHAT_ID
    config.json                  # deprecated stub
```

Root ops (outside `GO/` but GO-owned):

- `run_go.py` — entry (TokenStore, broker, token_watch, SingleLegMonitor)
- `scripts/stop_go.py`
- `Execution/Start Bots/start Go.sh` (+ `.bat`)
- `Execution/Stop Bots/stop Go.sh` (+ `.bat`)
- `tests/test_go_batman2_legs.py`

**Registries touched (not Phase 1 start-all):**

- `bat_telegram/loader.py` — `"go"` in `_KNOWN_BOTS`; config dir → `GO/telegram/bots`
- `core/runtime_logging.py` / `core/bot_logging.py` — `"go"`
- `core/bot_process_status.py` — `"go"` in `PHASE1_BOTS` with `optional` + `independent` (needed for lock/preflight; **not** in `PHASE1_CORE_BOTS` / start-phase1 order)
- `bat_telegram/alive_branding.py` — `"go"` logo alias (alive card still uses shared brand logo)

---

## Phase 1 boundary

- **Not** in `PHASE1_CORE_BOTS` / `PHASE1_OPTIONAL_BOTS` start order
- **Not** started by `start-phase1` / `batman-phase1.target`
- Own lock: `go.lock`
- Own process: `run_go.py`
- Own book under runtime `data/go/books/` — **never** writes `batman_*.json`
- Does **not** couple to KAVACH register, ATO, or `position_scope` IC roles

**OK to share:** TokenStore JWT, broker factory, mode gates, NIFTY LTP cache (read-only)

---

## Batman 2.0 leg math (center = operator NIFTY level `L`)

Base buy qty `Q` = `base_lots × lot_size`. Dyn hedge qty = floor(0.30 × Q / lot_size) × lot_size (0 if &lt; 1 lot). Strikes snapped to step 50 (half-up).

| Leg | Side | Strike | Qty |
|-----|------|--------|-----|
| CE buy | BUY CE | L+250 | Q |
| CE sell | SELL CE | L+300 | 2Q |
| CE dyn hedge | BUY CE | L+500 (sell+200) | 30% Q |
| CE margin hedge | BUY CE | L+1000 | Q |
| PE buy | BUY PE | L−250 | Q |
| PE sell | SELL PE | L−300 | 2Q |
| PE dyn hedge | BUY PE | L−500 (sell−200) | 30% Q |
| PE margin hedge | BUY PE | L−1000 | Q |

**Place sequence:** CE Buy → CE Margin → CE Sell → PE Buy → PE Margin → PE Sell → CE Dyn → PE Dyn  

On leg failure: stop remaining; book `partial`; no auto-unwind (v1).

---

## Single-leg exit

1. At entry: fixed SL ₹ and Target ₹ (option **premium**).
2. Monitor option LTP → hit SL or Target → SELL exit.
3. After trail activate (premium rise ≥ param): ratchet trailing SL and trailing Target.
4. Operator **Exit** → flatten that leg only.

Params (in `params.json`): `default_sl_rupees`, `default_target_rupees`, `trail_activate_rupees`, `trail_sl_distance`, `trail_target_distance`.

---

## Telegram UI (current)

Pattern: `reply_alive_card` → logo + HTML caption + inline keyboard (same as KAVACH 2.0).

**Caption:** `🟢 GO ACTIVE` · Env mode · Trade mode (Single/Multi) · timestamp · Broker · Book  

**Buttons (GO only):**

| Row | Buttons |
|-----|---------|
| 1 | ○/✅ Single-leg \| ○/✅ Multi-leg |
| 2 | 📊 GO Status \| 📖 Open Book |
| 3a (single) | 🟢 Buy CE \| 🔴 Buy PE |
| 3b (single) | 🚪 Exit Position |
| 3 (multi) | 🦇 Deploy Batman 2.0 |
| last | 🏠 Home \| ❓ Help |

Wizards:

- Multi: NIFTY level → lots → preview → Confirm  
- Single: strike/ATM → lots → SL ₹ → Target ₹ → Confirm  

Callbacks use `reply` under the photo card (do not `edit_message_text` on photo).

---

## What was completed this session

1. Scaffolded independent `GO/` package + `run_go.py` / start-stop scripts  
2. Design lock + Batman 2.0 calculator + unit tests  
3. Multi-leg sequential entry + GO book  
4. Single-leg entry / trail monitor / Exit  
5. Wired TokenStore + broker + token_watch in `run_go.py`  
6. Registered `go` for loader / logging / instance guard (independent)  
7. Configured Telegram token + chat; JWT saved to shared TokenStore  
8. UI upgraded to KAVACH-style alive card with GO buttons  

---

## Next session — pick up here

Suggested next work (not done yet):

1. **UAT/Prod order test** — switch mode if you want virtual/live fills (dev blocks live POST)  
2. **First multi-leg dry run** in UAT — Deploy Batman 2.0 with a center level  
3. **First single-leg dry run** — Buy CE/PE + confirm SL/trail behaviour  
4. Optional: GO-specific robot profile photo under `image/robot/go.*`  
5. Optional: expiry picker in wizard (today auto nearest weekly)  
6. Do **not** wire into Phase 1 start-all unless explicitly requested  

**Handoff phrase for new chat:**  
“Continue GO from `GO/GO_CONTEXT.md` — independent bot, KAVACH-style UI, multi-leg + single-leg already coded.”

---

## Non-goals (v1)

- Multi-leg exit / ATO / overnight dyn remainder / Extra Leg  
- Zerodha basket (execute on Dhan)  
- Phase 1 fleet integration  
- Auto-unwind of partial multi-leg fills  
