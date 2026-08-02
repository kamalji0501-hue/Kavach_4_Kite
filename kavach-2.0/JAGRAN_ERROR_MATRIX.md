# Batman v3 - JAGRAN Error Matrix

Last updated: 2026-05-17
Purpose: Maintain the source-wise allowlist of incidents that qualify for JAGRAN routing.

## Rules

- This is an allowlist plus staging sheet for iterative refinement.
- Every listed item must be dual-published: source chat plus JAGRAN.
- Starting policy: broad reporting with verbose repeats, then refine into Critical/Warning/Info.
- Error display default: prefer extracted raw broker/API error text.
- Timestamp default: `HH:MM IST, DD Mon YYYY`.
- Incident ID should be shown when available.
- Websocket-drop escalation: DRISHTI can alert locally on each drop; JAGRAN escalates when retry count reaches 5.
- Recovery notifications should be sent to JAGRAN for incidents routed to JAGRAN.
- JAGRAN should also include an end-of-day digest.

## Matrix

| Source    | Scenario                                                              | Route To Source Chat | Route To JAGRAN | Proposed Severity | Status          | Notes                                                                                   |
| --------- | --------------------------------------------------------------------- | -------------------- | --------------- | ----------------- | --------------- | --------------------------------------------------------------------------------------- |
| DRISHTI   | LTP/validation fetch failure after retry exhaustion                   | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | User attention needed because health/validation failed despite retries                  |
| DRISHTI   | Broker disconnected / broker connection failure                       | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Immediate attention incident                                                            |
| DRISHTI   | Token expired/stale event                                             | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Route to both DRISHTI and JAGRAN                                                        |
| DRISHTI   | Token update/validation failure requiring user attention              | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Keep raw broker/API error visible                                                       |
| DRISHTI   | Websocket drop (local alert on every drop)                            | Yes                  | No              | Warning           | LOCKED_20260517 | DRISHTI alerts each drop and retry progress/count                                       |
| DRISHTI   | Websocket retry exhaustion (retry count >= 5)                         | Yes                  | Yes             | Critical          | LOCKED_20260517 | Escalate to JAGRAN once retry threshold is reached                                      |
| KAVACH    | Margin shortfall                                                      | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Immediate-action trading risk                                                           |
| KAVACH    | Order rejection                                                       | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Immediate-action trading risk                                                           |
| KAVACH    | Emergency exit failure                                                | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Critical failure                                                                        |
| KAVACH    | Archive/completion failure with immediate operational impact          | Yes                  | Yes             | Critical          | CONFIRMED_SEED  | Closing flow failure                                                                    |
| SANCHALAK | Downstream bot failure during globally authorized run                 | Yes                  | Yes             | Warning           | LOCKED_20260517 | SANCHALAK action policy currently alert-only during testing                             |
| SARANSH   | Summary delivery channel failure (Telegram/file partial or full fail) | Yes                  | Yes             | Warning           | LOCKED_20260517 | Alert must include per-channel result details, including what completed and what failed |

## Pending Questions

1. Finalize exact Critical/Warning/Info labels per scenario after initial broad reporting observation.
2. Confirm JAGRAN EOD digest structure and fields.
3. Confirm whether any DRISHTI/KAVACH scenarios should later become local-only after refinement.
