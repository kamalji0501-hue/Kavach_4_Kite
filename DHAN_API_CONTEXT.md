# DhanHQ API Context — Batman Algo Reference

Last updated: 2026-06-05  
Owner: Rahul  
Official docs: https://dhanhq.co/docs/v2/

> **Living reference for agents and developers.** Read this before integrating any Dhan feature.  
> NIFTY LTP ownership rules → `NIFTY_LTP_POLICY.md`  
> Phase 1 wiring notes → `PHASE1_DHAN_INTEGRATION.md`

---

## 1. Scope — what Batman uses vs ignores

### In scope (Phase 1 + production)

| Need | Dhan area |
|------|-----------|
| NIFTY index LTP (ATO breach/retrace) | Market Quote REST + Live WebSocket feed |
| Open positions (register wizard) | `GET /positions` |
| Place ATO protect BUY / hedge SELL | `POST /orders` (MARKET, MARGIN) |
| Order status / rejection handling | `GET /orders/{id}`, orderbook, trades |
| Available margin before orders | `GET /fundlimit`, `POST /margincalculator` |
| Token validity probe | `GET /fundlimit`, `GET /profile` |
| JWT auth (daily via DRISHTI) | Access token from web.dhan.co |
| Option symbols → security IDs | Instrument CSV / Tradehull helpers |
| **Option LTP (display / pre-trade check)** | `POST /marketfeed/ltp` with `NSE_FNO` securityIds |

### Out of scope (do not integrate unless operator asks)

- Technical indicators / conditional triggers (`/conditional`, Tradehull `place_conditional_trigger`)
- Super orders, forever orders, bracket/cover order builders
- Option greeks, Heikin-Ashi, Renko, resample utilities
- Full market depth streaming (unless hedge UX needs it later)
- Partner OAuth / API-key browser login (we use manual JWT)
- SARANSH 5-year backtest historical pull (deferred — see §12)

---

## 2. Python libraries in this project

| Package | Version | Role in Batman |
|---------|---------|----------------|
| **`dhanhq`** | `2.2.0rc1` | NIFTY WebSocket feed (`MarketFeed` v2), optional direct REST |
| **`Dhan-Tradehull`** | `>=3.2.0` | Orders, positions, margin, option chain via `BatmanBroker` |

### When to use which

| Task | Library | Batman entry point |
|------|---------|-------------------|
| NIFTY LTP continuous feed | `dhanhq` | `core/nifty_ltp_feed.py`, `core/nifty_ltp_websocket_feed.py` |
| NIFTY LTP one-shot / token probe | `httpx` direct REST | `core/nifty_ltp.py` |
| Place / cancel orders | Tradehull → Dhan REST | `core/broker.py` → `place_order()` |
| Positions DataFrame | Direct REST (preferred) | `core/positions.py` → `fetch_positions_rest()` |
| Positions via broker wrapper | Tradehull | `BatmanBroker.get_positions()` |
| Option chain / strike helpers | Tradehull | `get_option_chain`, `ATM_Strike_Selection` (legacy modules) |
| **Option LTP by securityId** | httpx REST | `core/dhan_market_quote.py` → `BatmanBroker.get_fno_ltp_by_security_ids()` |

**Rule:** Do not add a third Dhan client path without updating this file.

---

## 3. Base URL, headers, auth

| Item | Value |
|------|-------|
| REST base | `https://api.dhan.co/v2/` |
| Auth header | `access-token: {JWT}` |
| Client header | `client-id: {dhanClientId}` — **required** for marketfeed/quote APIs |
| Token TTL | 24 hours (generate at web.dhan.co → Access DhanHQ APIs) |
| Renew | `POST /RenewToken` — only while token still active |
| Profile check | `GET /profile` → `tokenValidity`, `dataPlan`, `activeSegment` |

### Static IP (SEBI) — orders only

**Required for:** `POST/PUT/DELETE` on orders, super orders, forever orders.  
**Not required for:** positions, fundlimit, marketfeed LTP, profile, order **read** APIs.

Set via Dhan Web or `POST /ip/setIP`. Mandatory before VPS live trading.

### Data API subscription

Live LTP/quotes need paid Data plan. Profile: `dataPlan: Active`.  
Error **806** / **DH-902** if not subscribed.

---

## 4. Rate limits (official)

| Category | Per second | Per day | Batman usage |
|----------|------------|---------|--------------|
| **Order APIs** | 10 | 7,000 | ATO BUY/SELL bursts |
| **Data APIs** | 5 | 100,000 | Historical (SARANSH later) |
| **Quote APIs** | **1** | Unlimited | REST NIFTY LTP poll — **one collector only** |
| **Non-trading** | 20 | Unlimited | fundlimit, positions, profile |

Order modifications: max **25** per order.  
Quote API = why DRISHTI is the sole REST poller (`NIFTY_LTP_POLICY.md`).

WebSocket feed: not counted as REST quote limit; max **5 connections** / user.

---

## 5. NIFTY LTP (summary — details in NIFTY_LTP_POLICY.md)

| Method | Endpoint / URL | Notes |
|--------|----------------|-------|
| REST snapshot | `POST /marketfeed/ltp` | Body: `{"IDX_I": [13]}`. Max 1000 instruments, **1 req/sec** |
| REST OHLC | `POST /marketfeed/ohlc` | Not used Phase 1 |
| WebSocket v2 | `wss://api-feed.dhan.co?version=2&token=…&clientId=…&authType=2` | RequestCode **15** = ticker (LTP). Binary packets |
| NIFTY instrument | Segment `IDX_I` (enum 0), **securityId 13** | Locked in reference code |

**Batman:** consumers read `data/nifty_ltp_cache.json` only — never Dhan for spot on ATO path.

### Option LTP (NSE F&O) — same marketfeed API

Docs: https://dhanhq.co/docs/v2/market-quote/

| Item | Value |
|------|-------|
| Endpoint | `POST /marketfeed/ltp` (same as index) |
| Body | `{"NSE_FNO": [securityId, ...]}` — max 1000 IDs per request |
| Headers | `access-token` + **`client-id`** (both required) |
| Response | `data.NSE_FNO.{securityId}.last_price` |
| Rate limit | Quote APIs: **1 req/sec** — batch all legs in one POST |
| Subscription | Data API plan must be **Active** (profile `dataPlan`) |

**Do not use** Tradehull `get_ltp_data(names=["NIFTY 09 JUN …"])` for options — symbol format often fails with *"Check the Tradingsymbol"* even when JWT and NIFTY index LTP work.

**Batman path:**

1. Resolve strike + **expiry from `positions.json`** (any weekly — e.g. 09 Jun, 16 Jun) → `securityId` + canonical `tradingSymbol` via `instrument_master.py` + `core/nifty_option_expiry.py`.
2. Fetch LTP: `core/dhan_market_quote.fetch_fno_ltp_rest()` or `BatmanBroker.get_nifty_option_ltps()`.
3. UAT `/positions` enrich: `core/uat_position_enrich.try_marketfeed_option_premiums()` (fixture Sensibull prices first, then live marketfeed, then option chain fallback).

**Probe (agent/operator):**

```powershell
.venv\Scripts\python.exe scripts\probe_dhan_option_ltp.py
```

**WebSocket:** subscribe `ExchangeSegment: NSE_FNO` + `SecurityId` from instrument master (RequestCode 15 ticker) — same Data subscription; not wired for option polling in Phase 1 (REST batch on Positions refresh is enough).

### dhanhq feed methods (reference)

```python
from dhanhq import DhanContext
from dhanhq.marketfeed import MarketFeed

# Instrument tuple: (exchange_segment_int, security_id_str, request_code)
feed = MarketFeed(dhan_context=ctx, instruments=[(0, "13", 15)], version="v2")
await feed.connect()
tick = await feed.get_instrument_data()  # {"LTP": ..., ...}
```

### dhanhq REST quote helpers (if bypassing httpx)

- `dhan.ticker_data({"IDX_I": [13]})` — same as marketfeed/ltp
- `dhan.quote_data(...)` — full quote + depth (heavier)

---

## 6. Orders — ATO buy/sell (primary integration surface)

Docs: https://dhanhq.co/docs/v2/orders/

### Endpoints

| Method | Path | Static IP? | Use |
|--------|------|------------|-----|
| POST | `/orders` | **Yes** | Place ATO protect BUY, hedge SELL |
| PUT | `/orders/{order-id}` | **Yes** | Modify pending LIMIT |
| DELETE | `/orders/{order-id}` | **Yes** | Cancel pending |
| POST | `/orders/slicing` | **Yes** | Qty over freeze limit (large lots) |
| GET | `/orders` | No | Day orderbook |
| GET | `/orders/{order-id}` | No | Status poll |
| GET | `/orders/external/{correlation-id}` | No | Track by our ID |
| GET | `/trades` | No | Day fills |
| GET | `/trades/{order-id}` | No | Fills for one order |

### Place order — fields Batman cares about

```json
{
  "dhanClientId": "1106926362",
  "correlationId": "ato-ce-protect-001",
  "transactionType": "BUY",
  "exchangeSegment": "NSE_FNO",
  "productType": "MARGIN",
  "orderType": "MARKET",
  "validity": "DAY",
  "securityId": "49081",
  "quantity": 65,
  "price": 0,
  "triggerPrice": 0
}
```

| Field | Batman typical value | Notes |
|-------|---------------------|-------|
| `exchangeSegment` | `NSE_FNO` | NIFTY options |
| `productType` | `MARGIN` | Carry-forward F&O (Tradehull: `trade_type="MARGIN"`) |
| `orderType` | `LIMIT` (ATO) | ATO protect uses aggressive LIMIT (LTP ± buffer); other modules may still use MARKET until migrated |
| `transactionType` | `BUY` / `SELL` | Protect leg = BUY; exit hedge = SELL |
| `validity` | `DAY` | |
| `securityId` | From instrument master | Prefer ID over symbol string |
| `correlationId` | Optional, max 30 chars | `[a-zA-Z0-9 _-]` — good for ATO traceability |
| `quantity` | Multiples of lot (65 NIFTY) | Use slicing API if above freeze qty |

### Order status enum (poll until terminal)

`TRANSIT` → `PENDING` → `PART_TRADED` → `TRADED` | `REJECTED` | `CANCELLED` | `EXPIRED`

Batman `confirm_order()` in `core/resilience.py` polls until `TRADED` or `REJECTED`.

### Tradehull mapping (current `BatmanBroker.place_order`)

```python
tsl.order_placement(
    tradingsymbol=symbol,       # e.g. "NIFTY 10 MAR 25500 CALL"
    exchange="NFO",
    quantity=qty,
    price=price,
    trigger_price=trigger_price,
    order_type=order_type,      # MARKET | LIMIT | STOPLIMIT | STOPMARKET
    transaction_type=transaction_type,  # BUY | SELL
    trade_type=trade_type,      # MARGIN for carry-forward F&O
)
```

Related Tradehull: `cancel_order`, `get_order_status`, `get_orderbook`, `get_trade_book`, `place_slice_order`, `margin_calculator`.

### dhanhq direct order methods (alternative to Tradehull)

```python
from dhanhq import dhanhq
d = dhanhq(client_id, access_token)
d.place_order(...)       # wraps POST /orders
d.modify_order(...)
d.cancel_order(...)
d.get_order_by_id(...)
d.get_order_list()
d.get_trade_book()
d.place_slice_order(...)
d.margin_calculator(...)
```

Use Tradehull for Phase 1 unless unifying SDK later.

---

## 7. Positions & portfolio

Docs: https://dhanhq.co/docs/v2/portfolio/

| Method | Path | Static IP? | Batman use |
|--------|------|------------|------------|
| GET | `/positions` | No | **Register wizard** — `core/positions.py` |
| GET | `/holdings` | No | Delivery holdings (not Phase 1 ATO) |
| POST | `/positions/convert` | No | Intraday ↔ CNC (not Phase 1) |
| DELETE | `/positions` | **Yes** | Exit all — **disabled Phase 1** |

### Position fields for NIFTY options register

| Field | Use |
|-------|-----|
| `tradingSymbol` | Match CE/PE sell legs |
| `netQty` | Sign = long/short; wizard filters NIFTY options |
| `exchangeSegment` | `NSE_FNO` |
| `productType` | `MARGIN` |
| `drvExpiryDate` | Expiry label |
| `drvOptionType` | `CALL` / `PUT` |
| `drvStrikePrice` | Strike |
| `securityId` | For future order placement by ID |

Headers: `access-token` + `client-id`.

---

## 8. Funds & margin

Docs: https://dhanhq.co/docs/v2/funds/

| Method | Path | Use |
|--------|------|-----|
| GET | `/fundlimit` | DRISHTI token probe; available balance |
| POST | `/margincalculator` | Pre-check margin for one ATO order |
| POST | `/margincalculator/multi` | Multi-leg margin (iron condor context) |

### fundlimit response (key fields)

- `availabelBalance` — typo in API; usable to trade
- `utilizedAmount`, `sodLimit`, `withdrawableBalance`

Tradehull: `get_balance()`, `margin_calculator()`.

**JAGRAN scenario:** order rejected / insufficient margin — check before live VPS.

---

## 9. Exchange segments & product types (Annexure)

### Segments

| Enum | Segment | Batman |
|------|---------|--------|
| `IDX_I` | Index | NIFTY LTP (id **13**) |
| `NSE_FNO` | NSE F&O | All NIFTY options orders |
| `NSE_EQ` | NSE equity | Not Phase 1 |

### Product types

| Type | Meaning | Batman |
|------|---------|--------|
| `MARGIN` | Carry-forward F&O | **Default for ATO options** |
| `INTRADAY` | Intraday | Not used |
| `CNC` | Delivery equity | Not used |

### Order types

| Type | Use |
|------|-----|
| `MARKET` | ATO protect MARKET BUY (primary) |
| `LIMIT` | If limit protect needed |
| `STOP_LOSS` / `STOP_LOSS_MARKET` | Not Phase 1 ATO |

---

## 10. Instrument master

| Resource | URL |
|----------|-----|
| Compact CSV | https://images.dhan.co/api-data/api-scrip-master.csv |
| Detailed CSV | https://images.dhan.co/api-data/api-scrip-master-detailed.csv |
| Segment API | `GET /instrument/{exchangeSegment}` |

Map `tradingSymbol` ↔ `securityId` for order API.  
Tradehull: `get_instrument_file()`, `get_lot_size()`.

NIFTY lot size: **65** (verify on register day from master / broker).

---

## 11. Postback (webhooks) — VPS future

Docs: https://dhanhq.co/docs/v2/postback/

- JSON POST to operator URL on order status change
- Set Postback URL when generating token on web.dhan.co
- Cannot use `localhost` — needs public VPS URL
- **Alternative today:** poll `GET /orders/{id}` (what `confirm_order` does)

Payload includes: `orderId`, `orderStatus`, `filled_qty`, `omsErrorDescription`, `correlationId`.

Defer until VPS; reduces polling load for live ATO.

---

## 12. Historical data (SARANSH — deferred)

Docs: https://dhanhq.co/docs/v2/historical-data/

| Path | Use |
|------|-----|
| `POST /charts/intraday` | 1/5/15/25/60 min, last 5 years |
| `POST /charts/historical` | Daily OHLC |

Constraints: max **90 days** per intraday request; 5 req/sec; 100k/day.  
dhanhq: `intraday_minute_data()`, `historical_daily_data()`.  
Tradehull: `get_historical_data()`, `get_long_term_historical_data()`.

Not Phase 1 gate — chunk + cache when SARANSH starts.

---

## 13. Error codes (keep for JAGRAN messages)

### Trading API (DH-9xx)

| Code | Meaning |
|------|---------|
| DH-901 | Invalid / expired token |
| DH-902 | Data API not subscribed or no trading access |
| DH-903 | Account / segment issue |
| DH-904 | **Rate limit** |
| DH-905 | Bad request parameters |
| DH-906 | Order error |
| DH-907 | Data error |
| DH-908 | Server error |

### Data API (8xx)

| Code | Meaning |
|------|---------|
| 806 | Data APIs not subscribed |
| 805 | Too many connections / requests |
| 807–809 | Token expired / invalid |
| 813 | Invalid securityId |

Batman extracts errors in `core/nifty_ltp._extract_dhan_error()` and broker wrappers.

---

## 14. Batman code map (quick lookup)

| Capability | File | Dhan surface |
|------------|------|--------------|
| NIFTY LTP REST | `core/nifty_ltp.py` | `POST /marketfeed/ltp` (`IDX_I`) |
| Option LTP REST | `core/dhan_market_quote.py` | `POST /marketfeed/ltp` (`NSE_FNO`) |
| Option LTP probe | `scripts/probe_dhan_option_ltp.py` | JWT + NIFTY + FNO batch test |
| NIFTY LTP feed | `core/nifty_ltp_feed.py` | REST poller + external watch |
| NIFTY LTP WS backup | `core/nifty_ltp_websocket_feed.py` | WebSocket v2 |
| LTP policy | `NIFTY_LTP_POLICY.md` | Architecture |
| Positions | `core/positions.py` | `GET /positions` |
| Orders | `core/broker.py` | Tradehull → `/orders` |
| Order confirm | `core/resilience.py` | `GET /orders/{id}` |
| ATO logic | `modules/ato_protection.py` | Cache LTP + `place_order` |
| Token store | `core/token_store.py` | JWT persistence |
| DRISHTI feed UI | `bat_telegram/bots/drishti/nifty_feed_integration.py` | Feed setup |

---

## 15. Integration checklist (live VPS)

- [ ] Static IP whitelisted on Dhan account
- [ ] Data API subscription active
- [ ] DRISHTI single instance + LTP cache healthy
- [ ] `productType=MARGIN`, `exchangeSegment=NSE_FNO` on all option orders
- [ ] `securityId` resolved for each leg (not symbol-only)
- [ ] Margin calculator before first real ATO of day
- [ ] Postback URL on VPS (optional upgrade from poll)
- [ ] Order rate: stay under 10/sec burst
- [ ] Mock mode off only on VPS after operator sign-off

---

## 16. Doc index (full Dhan site)

| Section | URL | Batman relevance |
|---------|-----|------------------|
| Introduction / limits | /docs/v2/ | Always |
| Authentication | /docs/v2/authentication/ | JWT, static IP, TOTP |
| Orders | /docs/v2/orders/ | **Core** |
| Portfolio | /docs/v2/portfolio/ | **Core** |
| Funds | /docs/v2/funds/ | Margin checks |
| Market Quote | /docs/v2/market-quote/ | REST LTP |
| Live Market Feed | /docs/v2/live-market-feed/ | WebSocket LTP |
| Postback | /docs/v2/postback/ | VPS later |
| Instruments | /docs/v2/instruments/ | securityId lookup |
| Historical | /docs/v2/historical-data/ | SARANSH later |
| Super Order | /docs/v2/super-order/ | **Ignore** Phase 1 |
| Annexure | /docs/v2/annexure/ | Enums + error codes |

---

*Update this file when adding a new Dhan API call or changing SDK versions.*
