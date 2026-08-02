# NIFTY LTP — Single Source of Truth (LOCKED)



Last updated: 2026-07-23  

Owner: Rahul



---



## Rule



**Only DRISHTI orchestrates NIFTY LTP collection for production trading.** All other bots and modules **read the shared NIFTY cache only** — they never call Dhan for NIFTY spot.



**Auth:** existing JWT / access-token only (no PIN/TOTP).



Both collectors are first-class (operator chooses in LTP Feed Setup):

- **WebSocket** (`feed_mode=websocket`, default) — in-process Dhan MarketFeed v2
- **REST** (`feed_mode=rest`) — DRISHTI polls `POST /v2/marketfeed/ltp`



One-shot `fetch_nifty_ltp` uses WebSocket first, then REST fallback on connection failure.



**GIFT Nifty** is a separate **validation-only** off-hours probe — it does **not** replace NIFTY spot for KAVACH/ATO.



| Role | Component | Dhan API? | Writes cache? |

|------|-----------|-----------|---------------|

| **Collector (WebSocket)** | DRISHTI `NiftyLtpWebSocketFeedService` (`feed_mode=websocket`) | Yes — WebSocket v2 in-process | same NIFTY cache |

| **Collector (REST)** | DRISHTI `NiftyLtpFeedService` (`feed_mode=rest`) | Yes — REST `marketfeed/ltp` | `nifty_ltp_cache.json` |

| **Off-hours validation** | DRISHTI `GiftNiftyProbeService` | Yes — GIFTNIFTY REST | `gift_nifty_ltp_cache.json` |

| **Consumers** | KAVACH, ATO (`ato_protection`), SARANSH (future) | **No** | Read NIFTY cache only |

| **Diagnostic** | DRISHTI WebSocket health button / `smoke_nifty_ltp_rest.py` | Yes — optional | No / cache for smoke |



---



## Shared caches



| File | Purpose |

|------|---------|

| `data/nifty_ltp_cache.json` | Production NIFTY snapshot (KAVACH/ATO) |

| `data/gift_nifty_ltp_cache.json` | Off-hours GIFT validation snapshot (DRISHTI only) |

| `data/nifty_ltp_feed_config.json` | Feed settings incl. ping warning/critical thresholds |



### Audit logs (`logs_{uat|prod}/runtime/YYYY-MM/YYYY-MM-DD/drishti/logs/`)



| Folder / file | Purpose |

|---------------|---------|

| `nifty_websocket_ltp/ws_ltp_YYYYMMDD.log` | WebSocket ticks (`HH:MM:SS.mmm \| LTP`) |

| `nifty_rest_ltp/rest_ltp_YYYYMMDD.log` | REST poll ticks (`HH:MM:SS.mmm \| LTP`) |

| `nifty_ltp/gift_nifty_ltp_YYYYMMDD.log` | GIFT validation ticks (legacy CSV format) |



**Feed stale (not unchanged price):** WebSocket — no tick refresh for **5s** → critical. REST — no poll for **10s** → critical.



---



## Freshness rules



### Background feed (NSE hours 09:15–15:30 IST)



Cache age must be ≤ **5s** (WebSocket modes) or **10s** (REST) — based on last tick/poll time, not price change.



### User ping (Telegram — configurable via LTP Feed Setup)



| Threshold | Default | Action |

|-----------|---------|--------|

| Feed freshness | poll×3 (e.g. 6s @ 2s poll) | Show from cache during market |

| **Ping warning** | **15s** | ⚠️ warning + live REST fetch |

| **Ping critical** | **60s** | 🔴 JAGRAN `nifty_ltp_stale_cache` + live fetch |



Warning must be ≥ feed freshness. Critical must be ≥ warning + 15s.



---



## GIFT Nifty (off-hours validation)



| Field | Value |

|-------|-------|

| Dhan symbol | `GIFTNIFTY` |

| Security ID | **5024** |

| Segment | `IDX_I` |

| Instrument CSV | `Dependencies/all_instrument *.csv` |



- Polls when NSE cash session is **closed**

- Idle during 09:15–15:30 IST (production NIFTY feed active)

- Telegram: **GIFT Nifty (probe)** button



---



## Feed modes



### `websocket` (recommended trial)



- DRISHTI runs in-process WebSocket v2 inside `run_drishti.py`.

- Audit: `nifty_websocket_ltp/ws_ltp_YYYYMMDD.log` (batch flush 1s).

- Feed stale critical if no tick for **5s** (unchanged price still counts as fresh).



### `rest`



- DRISHTI polls `POST /v2/marketfeed/ltp` every **2s** (configurable 1/2/3/5).

- Audit: `nifty_rest_ltp/rest_ltp_YYYYMMDD.log`.

- Feed stale critical if no successful poll for **10s**.

- One DRISHTI process only — duplicate instances cause 429 rate limits.



## Consumer contract



```python

from core.nifty_ltp_feed import resolve_nifty_ltp_from_cache



spot = resolve_nifty_ltp_from_cache(max_age_seconds=6.0)  # raises if stale

```



- **No** `broker.get_nifty_ltp()` on trading paths (ATO, register decisions).

- Stale/missing cache → ATO skips tick, counts failure, JAGRAN after threshold, auto-pause.



---



## Ops checklist



1. One `run_drishti.py` instance — use `Execution\Start Bots\start Drishti.bat` for overnight

2. Fresh JWT via DRISHTI each morning

3. Dhan Data API subscription active

4. **Nifty LTP (Polling)** — live fetch if stale; cache if fresh during market

5. **GIFT Nifty (probe)** — off-hours connectivity check

6. Tail audit logs for post-mortem

7. Reconfigure thresholds: **LTP Feed Setup** → steps 4–5



---



## Related docs



- `CONTEXT.md` §18

- `bat_telegram/bots/drishti/DRISHTI_CONTEXT.md` §5, §13

- `LOGGING_LAYOUT.md`

- `PHASE1_DHAN_INTEGRATION.md`


