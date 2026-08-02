# Production / VPS Deployment — Open Items

Last updated: 2026-06-07  
Owner: Rahul

> **UAT is authoritative until VPS is purchased.**  
> Week-1 trial: **WebSocket only** on laptop UAT (`logs_uat`, `config/batman_mode.json` → `uat`).

---

## Locked for UAT (do not change without explicit decision)

| Decision | Choice |
|----------|--------|
| Feed mode (trial week) | **WebSocket only** (`feed_mode=websocket`) |
| Default feed (target) | **WebSocket** for new configs (UAT + future prod) |
| DRISHTI + KAVACH separate | **Yes — final** (no merge) |
| Stale feed behavior | **ATO auto-pause + JAGRAN critical** (5s no tick during market) |
| Verification primary | **Log files** (`nifty_websocket_ltp/ws_ltp_*.log`) |
| Telegram Nifty buttons | **Cache-only** (no new Dhan connections) — *to implement* |
| Market-hours gate | **09:15–15:30 IST on NSE trading calendar** — no stale/JAGRAN noise when closed — *harden* |
| WS startup grace | **~30s** to connect + first tick before feed marked healthy — *to implement* |

---

## UAT implementation backlog (before / during week-1)

| ID | Item | Priority |
|----|------|----------|
| UAT-1 | Change `default_feed_mode` → `websocket` in `telegram/bots/drishti/params.json` | P0 |
| UAT-2 | WS startup: wait up to 30s for first tick; block “feed healthy” until then | P0 |
| UAT-3 | Off-hours: no feed-stale watchdog, no JAGRAN `nifty_ltp_stale_cache`, no error spam in logs | P0 |
| UAT-4 | Telegram **Nifty LTP** buttons: cache-only + timestamp (no live REST fallback) | P1 |
| UAT-5 | Optional `/niftystatus` (mode, LTP, last tick, tick count) — convenience only | P2 |
| UAT-6 | Log archive 7–10 days | P3 (after trial) |

---

## Deferred (not UAT week-1)

- `auto` fallback (WS → REST)
- ATO monitor / executor queue (order non-blocking)
- Merge DRISHTI into KAVACH
- REST vs WS A/B on same week (UAT = WS only)

---

## Production / VPS — open questions (ask when VPS purchased)

| # | Question | Options | Notes |
|---|----------|---------|-------|
| P1 | Same `feed_mode=websocket` on VPS? | Yes / REST backup day first | UAT logs should decide |
| P2 | `logs_prod` path + DRISHTI start order | DRISHTI → KAVACH → JAGRAN | Same as laptop |
| P3 | WS startup grace on VPS | 30s / 60s | Slower network → maybe 60s |
| P4 | Critical JAGRAN chat on VPS | Same Batman Alerts group | Confirm token.env on VPS |
| P5 | Off-hours on VPS overnight | DRISHTI runs 24/7 but feed idle 09:15–15:30 only | No false stale |
| P6 | `dhanhq` RC pin | Keep RC / upgrade when GA | Review after UAT week |
| P7 | Static IP + prod mode | `config/batman_mode.json` → `prod` | `data/prod/` paths |
| P8 | Duplicate DRISHTI guard | One process only | 429 prevention |

---

## Go / no-go for prod (after UAT week)

Checklist:

- [ ] `ws_ltp_*.log` continuous lines full session (09:15–15:30)
- [ ] Zero false JAGRAN stale during market
- [ ] Zero JAGRAN stale **off-hours** (nights/weekends)
- [ ] KAVACH ATO no stale-cache pauses on good feed days
- [ ] Reconnect count acceptable in WS log
- [ ] First-tick within 30s of DRISHTI start (market open)

---

## Related docs

- `NIFTY_LTP_POLICY.md`
- `LOGGING_LAYOUT.md`
- `PHASE1_OPEN_QUESTIONS.md`
