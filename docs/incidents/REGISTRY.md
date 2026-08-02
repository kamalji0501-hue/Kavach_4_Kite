# Incident Registry Dashboard

*Auto-generated: 2026-06-25T13:52:54.433590+05:30*

## Summary metrics

| Metric | Count |
|--------|------:|
| Total incidents | 23 |
| Open | 0 |
| Closed | 23 |
| Critical | 3 |
| High | 17 |
| Medium | 2 |
| Low | 1 |
| Regression-linked | 11 |

## By category

| Category | Count |
|----------|------:|
| broker | 3 |
| configuration | 1 |
| connectivity | 2 |
| documentation | 1 |
| infrastructure | 3 |
| market_data | 8 |
| robot | 2 |
| runtime | 1 |
| testing | 2 |

## By robot

| Robot | Count |
|-------|------:|
| drishti | 12 |
| jagran | 1 |
| kavach | 5 |

## Top unstable modules

- `core/nifty_ltp_websocket_feed.py` — 6 incident(s)
- `core/nifty_ltp_feed.py` — 5 incident(s)
- `bat_telegram/bots/drishti/nifty_feed_integration.py` — 5 incident(s)
- `backtest_engine/shadow/shadow_broker.py` — 2 incident(s)
- `core/feed_recovery.py` — 2 incident(s)
- `core/nifty_ltp_failover.py` — 2 incident(s)
- `core/bot_supervisor.py` — 2 incident(s)
- `backtest_engine/resolver/instrument_master.py` — 1 incident(s)

## Open incidents

*None — all tracked incidents closed.*

## All incidents (index)

| ID | Title | Category | Status | First seen |
|----|-------|----------|--------|------------|
| [INC-2026-016](records/INC-2026-016.md) | Expired UAT fixture expiry blocks ShadowBroker boo | broker | closed | 2026-06-25 |
| [INC-2026-017](records/INC-2026-017.md) | Mid-session WebSocket false failover — stale watch | market_data | closed | 2026-06-25 |
| [INC-2026-018](records/INC-2026-018.md) | diagnose_robot.py reads wrong log root in UAT mode | documentation | closed | 2026-06-25 |
| [INC-2026-019](records/INC-2026-019.md) | PE managed qty mismatch after partial virtual ledg | testing | closed | 2026-06-25 |
| [INC-2026-020](records/INC-2026-020.md) | UAT E2E log scan flagged pre-fix errors in same-da | testing | closed | 2026-06-25 |
| [INC-2026-021](records/INC-2026-021.md) | JAGRAN Telegram publish timeout during morning fee | connectivity | closed | 2026-06-25 |
| [INC-2026-022](records/INC-2026-022.md) | DRISHTI cold-start without JWT + ATO pause/resume  | connectivity | closed | 2026-06-25 |
| [INC-2026-023](records/INC-2026-023.md) | DRISHTI cache replace race caused feed task exits  | market_data | closed | 2026-06-25 |
| [INC-2026-STAB-01](records/INC-2026-STAB-01.md) | UAT state-file split-brain — ATO pause written to  | configuration | closed | 2026-06-12 |
| [INC-2026-STAB-02](records/INC-2026-STAB-02.md) | KAVACH menu reads wrong pause state in UAT | robot | closed | 2026-06-12 |
| [INC-2026-STAB-03](records/INC-2026-STAB-03.md) | Failover state lost on DRISHTI restart | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-04](records/INC-2026-STAB-04.md) | WebSocket Previous Close frame treated as fatal er | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-05](records/INC-2026-STAB-05.md) | WebSocket HTTP 429 reconnect storm | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-06](records/INC-2026-STAB-06.md) | WS 429 cooldown exceeded stale threshold → false f | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-07](records/INC-2026-STAB-07.md) | Feed gating used save-age only, not JWT exp | broker | closed | 2026-06-12 |
| [INC-2026-STAB-08](records/INC-2026-STAB-08.md) | Startup lock / PID reuse failures | infrastructure | closed | 2026-06-12 |
| [INC-2026-STAB-09](records/INC-2026-STAB-09.md) | Auth errors retried and triggered failover | broker | closed | 2026-06-12 |
| [INC-2026-STAB-10](records/INC-2026-STAB-10.md) | KAVACH cold-start without JWT | robot | closed | 2026-06-12 |
| [INC-2026-STAB-11](records/INC-2026-STAB-11.md) | Supervisor ignored LTP gate failure | infrastructure | closed | 2026-06-12 |
| [INC-2026-STAB-12](records/INC-2026-STAB-12.md) | health.json not authoritative for RUNNING | infrastructure | closed | 2026-06-12 |
| [INC-2026-STAB-13](records/INC-2026-STAB-13.md) | Session REST lock with no same-day WS retry | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-14](records/INC-2026-STAB-14.md) | Live Price opened parallel one-shot WebSocket | market_data | closed | 2026-06-12 |
| [INC-2026-STAB-15](records/INC-2026-STAB-15.md) | Lock timeout without retry on state writes | runtime | closed | 2026-06-12 |
