# SARANSH — Open Questions (Trading Q&A format)

**Last updated:** 2026-06-12 (resume session)  
**Owner:** Rahul  
**Status:** 🔴 **0 / 25 answered** (void all 2026-06-07 chat answers)  
**Format:** Trading / operations language — see `reference/TRADING_QA_MASTER_PROMPT.md`  
**Design already locked (2026-06-05):** `telegram/design/saransh_design.md` — do not re-ask unless operator reopens  
**Code baseline:** ~95% — `SARANSH_IMPLEMENTATION_STATUS.md`

---

## Parallel track — tomorrow (DRISHTI / KAVACH, not SARANSH coding)

**Goal:** Prove Nifty WebSocket feed + logs + 09:25 ATO gate in UAT.  
**Runbook:** `docs/BATMAN_FEED_OPERATOR_RUNBOOK.md` §10 · handoff: `NEW_CHAT_HANDOFF.md`

| Time (IST) | Action |
|------------|--------|
| ~08:45 | Start DRISHTI, then KAVACH (fresh — not overnight) |
| ~08:45 | If token expired → **Update Token** on DRISHTI |
| ~08:55 | KAVACH **Register** → confirm |
| 09:15+ | NIFTY Status → websocket, cache updating |
| 09:15–09:25 | ATO Status → **Waiting until 09:25** |
| 09:25+ | Monitoring active; breach checks run |
| Session | Check WS log file grows; optional failover test |

**WebSocket tick log path (UAT):**  
`logs_uat/runtime/YYYY-MM/YYYY-MM-DD/drishti/logs/nifty_websocket_ltp/ws_ltp_YYYYMMDD.log`  
**Line format:** `HH:MM:SS.mmm | 25231.50` (one line per tick, batched flush ~1s)

**Also check:** `data/nifty_ltp_cache.json` updating · feed mode via DRISHTI **LTP Feed Setup** (not hand-edit config)

**SARANSH tomorrow:** Optional start — **not required** for feed UAT. SARANSH Q&A can continue without market test.

---

## Void session rule

All A/B/C answers from the **2026-06-07 SARANSH Cursor chat** are **invalid**. Re-answer every question below.

**Coding gate:** All batches answered → `docs/SARANSH_PHASE1_HANDOFF.md` approved → operator says **Start coding**.

---

# BATCH 1 — Reporting truth & sign-off scope

---

**QUESTION #1 — OQ-SAR-REV-01**

**Area:** Reporting — points lost

**Scenario:** After a choppy day, ATO Cycle shows **−4.5 points** net but Daily Summary shows **−6.2** “entry loss.” Which number is official for reviewing the day?

**Options:**  
**A.** Round-trip only (each completed buy→sell protect)  
**B.** Show both round-trip net and entry slippage vs sell strike  
**C.** Round-trip in Telegram; slippage detail only in Excel  
**D.** Custom  

**Recommended:** **A**  
**Why:** One truth per day; matches how you count ATO round trips.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #2 — OQ-SAR-REV-02**

**Area:** Reporting — end-of-day review

**Scenario:** Volatile day — **8 ATO round trips**. You review in Excel before tomorrow’s Register. What must the file contain?

**Options:**  
**A.** Cycle table only (side, strike, buy/sell Nifty, points, lots)  
**B.** Full audit trail (timestamps, triggers, protect strike, order ids)  
**C.** Cycle table on phone; full audit in EOD Excel only  
**D.** Custom  

**Recommended:** **B** for serious post-mortem; **C** if phone is enough intraday  
**Why:** Gate 5 needs audit when something looks wrong.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #3 — OQ-SAR-REV-03**

**Area:** Broker / token failure

**Scenario:** **15:35** auto recap. Dhan token dead but UAT shadow ATO ran and cycles are logged.

**Options:**  
**A.** Send recap from algo records; mark PnL/orders **unavailable**  
**B.** Skip auto recap until token fixed  
**C.** Send cycles + points only; skip PnL and orders  
**D.** Custom  

**Recommended:** **A**  
**Why:** You still want proof ATO ran; honest unavailable beats silence.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #4 — OQ-SAR-REV-04**

**Area:** Session lifecycle

**Scenario:** KAVACH Register **started** but **not confirmed**. You tap SARANSH ATO Cycle.

**Options:**  
**A.** Warning — no live session; empty slate  
**B.** Show whatever is on disk (may look like today’s trades)  
**C.** Last completed session with date stamp  
**D.** Custom  

**Recommended:** **A**  
**Why:** Register start wipes reporting slate; misleading data is risky.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #5 — OQ-SAR-REV-05**

**Area:** Sign-off — “SARANSH is done”

**Scenario:** You close the SARANSH workstream. What must work first?

**Options:**  
**A.** Menu recap + Excel + clean session after Batman Complete  
**B.** A + Telegram ack after Register confirm and Complete  
**C.** B + Non Critical chat alert if SARANSH process dies  
**D.** Custom  

**Recommended:** **B** normal ops; **C** if you want crash visibility  
**Why:** Session boundaries must match KAVACH.

**My Choice:**  
**Additional Notes:**

---

# BATCH 2 — Daily summary shape & data ownership

---

**QUESTION #6 — OQ-SAR-REV-06**

**Area:** Reporting — Daily Summary content

**Scenario:** You chose one official point-impact number (Q1). What else appears in the **Telegram** Daily Summary?

**Options:**  
**A.** Slim: session, orders, round trips, net points, holding, PnL, token line  
**B.** Slim + extra lines (trigger mix, time buckets) labelled “debug”  
**C.** Operator toggles sections on/off without code change  
**D.** Custom  

**Recommended:** **A**  
**Why:** Phone = recap; Excel = depth.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #7 — OQ-SAR-REV-07**

**Area:** Reporting — which trades in Excel

**Scenario:** Excel is built after a fresh Register confirm. Ledger file may contain **older** cycles.

**Options:**  
**A.** Only this Batman session (from deploy time + matching deployment)  
**B.** Everything that **exited today** regardless of session  
**C.** Entire ledger file every time  
**D.** Custom  

**Recommended:** **A**  
**Why:** Must not show yesterday’s book after new Register.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #8 — OQ-SAR-REV-08**

**Area:** Data ownership — who writes Excel during live ATO

**Scenario:** KAVACH still saves quick Excel snapshots on each cycle **and** SARANSH builds the operator report.

**Options:**  
**A.** SARANSH only — stop KAVACH Excel snapshots; keep CSV for live debug  
**B.** Both keep writing Excel  
**C.** SARANSH only — stop all KAVACH Excel; CSV snapshot OK for debug  
**D.** Custom  

**Recommended:** **C**  
**Why:** One official Excel; CSV still openable while algo runs.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #9 — OQ-SAR-REV-09**

**Area:** Monitoring — process crash

**Scenario:** SARANSH reporting bot dies mid-session. You are not watching the terminal.

**Options:**  
**A.** Log file only — you notice later  
**B.** Message to **Non Critical Alerts** when SARANSH dies  
**C.** Same as B for all bots (DRISHTI, KAVACH, JAGRAN, SARANSH)  
**D.** Custom  

**Recommended:** **B** for SARANSH wave; **C** later  
**Why:** Reporting bot failure should not use Batman Alerts (critical).

**My Choice:**  
**Additional Notes:**

---

**QUESTION #10 — OQ-SAR-REV-10**

**Area:** Reporting — when Excel refreshes

**Scenario:** You tap ATO Cycle several times during a fast market. When should the **detailed Excel** rebuild?

**Options:**  
**A.** Every ATO Cycle tap + Daily Summary + 15:35 auto  
**B.** Daily Summary + 15:35 only (ATO Cycle = Telegram text only)  
**C.** 15:35 only unless you run Daily Summary  
**D.** Custom  

**Recommended:** **B**  
**Why:** Full Excel is heavy; mid-day refresh via Daily Summary is enough.

**My Choice:**  
**Additional Notes:**  
*(Confirm: Telegram never receives Excel file attachment — text only.)*

---

# BATCH 3 — Session messages, ops context, cross-day

---

**QUESTION #11 — OQ-SAR-REV-11**

**Area:** Session messaging

**Scenario:** Session not armed (wizard open, or day after Complete). You open ATO Cycle or Daily Summary.

**Options:**  
**A.** Three messages: idle → “complete Register”; completed → “session over”; armed → normal recap  
**B.** One generic “no active session” line  
**C.** Warning on Status only; reports unchanged  
**D.** Custom  

**Recommended:** **A**  
**Why:** Wizard vs completed day need different operator cues.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #12 — OQ-SAR-REV-12**

**Area:** Reporting — why no ATO today

**Scenario:** End of day recap but ATO never fired — paused, waiting for 09:25, or feed manual handling.

**Options:**  
**A.** Algo paused line only  
**B.** Paused + monitoring state (waiting / active / manual) from shared status  
**C.** No ops lines — numbers only  
**D.** Custom  

**Recommended:** **B**  
**Why:** Explains empty cycle table without guessing.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #13 — OQ-SAR-REV-13**

**Area:** Delivery failure

**Scenario:** 15:35 recap — Telegram sends but disk log fails (or reverse).

**Options:**  
**A.** Log error only  
**B.** Alert in SARANSH chat with what failed  
**C.** Retry then alert if still failing  
**D.** Custom  

**Recommended:** **C** (see Q25 for retry count)  
**Why:** EOD recap must not fail silently.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #14 — OQ-SAR-REV-14**

**Area:** Cross-day round trip

**Scenario:** Buy protect **Monday**, sell protect **Tuesday**. Tuesday recap should show?

**Options:**  
**A.** Count on **Tuesday**; footnote if buy was prior day; full dates in Excel  
**B.** Show buy and sell times in Telegram table  
**C.** Tuesday Telegram normal; cross-day detail Excel only  
**D.** Custom  

**Recommended:** **A** (locked Q12 spirit)  
**Why:** Exit-day attribution; phone stays compact.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #15 — OQ-SAR-REV-15**

**Area:** Design-complete gate

**Scenario:** All questions answered. What document must you approve before coding?

**Options:**  
**A.** Update existing design + status files only  
**B.** New `docs/SARANSH_PHASE1_HANDOFF.md` (decisions + acceptance checklist)  
**C.** Add checklist to `GATE5_RUNBOOK.md` only  
**D.** Custom  

**Recommended:** **B**  
**Why:** Single sign-off artifact.

**My Choice:**  
**Additional Notes:**

---

# BATCH 4 — Excel on phone, retries, config

---

**QUESTION #16 — OQ-SAR-REV-16**

**Area:** Telegram vs Excel

**Scenario:** Operator asks for “the Excel” on phone.

**Options:**  
**A.** Never send Excel on Telegram — text only; file on disk path in Status  
**B.** Send Excel file on Telegram on Daily Summary  
**C.** Send Excel only on manual command  
**D.** Custom  

**Recommended:** **A**  
**Why:** Large files; path on Status is enough.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #17 — OQ-SAR-REV-17**

**Area:** Delivery — testing phase tone

**Scenario:** Recap fails after retries during UAT.

**Options:**  
**A.** Short alert: “summary failed”  
**B.** Full error detail in Non Critical chat (testing); shorten later  
**C.** Full detail always  
**D.** Custom  

**Recommended:** **B** for now  
**Why:** You said testing phase — refine later.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #18 — OQ-SAR-REV-18**

**Area:** Cross-day — buy time on phone

**Scenario:** Tuesday exit for Monday entry. Telegram footnote needs **buy time**.

**Options:**  
**A.** Store buy time in algo cycle record at sell (preferred)  
**B.** Look up from ledger when drawing Telegram table  
**C.** Skip footnote on phone; Excel only  
**D.** Custom  

**Recommended:** **A**  
**Why:** Clean recap without dual sources.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #19 — OQ-SAR-REV-19**

**Area:** Configuration — optional summary sections

**Scenario:** You want to turn off PnL line or ops block without developer.

**Options:**  
**A.** Wire all toggles in bot params  
**B.** Fixed template — change needs code  
**C.** Three toggles: PnL, ops block, token line  
**D.** Custom  

**Recommended:** **C**  
**Why:** Enough control; not overwhelming.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #20 — OQ-SAR-REV-20**

**Area:** Handoff doc location

**Scenario:** Same as Q15 — confirm handoff file name/location.

**Options:**  
**A.** `saransh_design.md` only  
**B.** `docs/SARANSH_PHASE1_HANDOFF.md`  
**C.** `SARANSH_CONTEXT.md` only  
**D.** Custom  

**Recommended:** **B**  
**Why:** Keeps design vs implementation sign-off separate.

**My Choice:**  
**Additional Notes:**

---

# BATCH 5 — EOD edge cases & Status button

---

**QUESTION #21 — OQ-SAR-REV-21**

**Area:** Auto EOD — idle day

**Scenario:** 15:35 on trading day but you never Register — no armed session.

**Options:**  
**A.** Still send slim recap (zeros / unavailable)  
**B.** Skip auto EOD if never armed  
**C.** Skip if no cycles and not armed  
**D.** Custom  

**Recommended:** **C**  
**Why:** Avoid noise on days you did not trade.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #22 — OQ-SAR-REV-22**

**Area:** Open protect in Excel

**Scenario:** You bought CE protect; market never triggered sell — open leg at EOD.

**Options:**  
**A.** Separate **Open legs** sheet in Excel  
**B.** Same ledger sheet with status Open/Closed  
**C.** Live state sheet only (minimal)  
**D.** Custom  

**Recommended:** **A**  
**Why:** Open risk visible at day end.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #23 — OQ-SAR-REV-23**

**Area:** Status button

**Scenario:** You tap Status to debug during UAT.

**Options:**  
**A.** Full: session, holding CE/PE, last Excel path/time, mode, EOD time  
**B.** Session + holding only  
**C.** Full + last delivery ok/fail  
**D.** Custom  

**Recommended:** **A** for UAT  
**Why:** One button to find Excel and session state.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #24 — OQ-SAR-REV-24**

**Area:** Legacy event log (telemetry CSV)

**Scenario:** KAVACH still writes row-per-event CSV alongside new cycle feed.

**Options:**  
**A.** SARANSH ignores for numbers; optional debug sheet in Excel during UAT  
**B.** SARANSH never reads it  
**C.** Stop writing event CSV from KAVACH  
**D.** Custom  

**Recommended:** **A** during UAT; **B** after Gate 5  
**Why:** Compare feeds once; then simplify.

**My Choice:**  
**Additional Notes:**

---

**QUESTION #25 — OQ-SAR-REV-25**

**Area:** Retry count (pairs with Q13)

**Scenario:** Telegram send fails at EOD — how hard to retry?

**Options:**  
**A.** 1 retry then alert  
**B.** 3 retries then one full error message  
**C.** Retry until success (cap 5)  
**D.** Custom  

**Recommended:** **B** for testing phase  
**Why:** Balance reliability vs spam.

**My Choice:**  
**Additional Notes:**

---

## Progress

| Metric | Value |
|--------|-------|
| Answered | 0 / 25 |
| Confidence to code | Low |
| Next step | Answer Batch 1 (#1–#5) in one reply |

---

*End — resume: answer Batch 1, then Batches 2–5 at 5 per session.*
