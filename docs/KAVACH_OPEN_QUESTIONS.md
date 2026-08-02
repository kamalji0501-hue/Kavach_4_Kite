# KAVACH / ATO — Open Questions (awaiting operator)

**Status:** Q1–Q62 **locked + coded** · Q63–Q98 **locked** *(Q86/Q88 skipped — N/A Quick Tune v1)* · **0 pending**  
**Design pack:** **`docs/KAVACH_ATO_CONFIGURATION_DESIGN.md`** (ATO Configuration / Quick Tune UI + behaviour)  
**Locked:** Q1–Q98 in this file *(Q86/Q88 skipped)* + `docs/KAVACH_ATO_OPERATOR_RULES.md`  
**Resume pack:** `docs/KAVACH_Tuesday_RESUME.md` (Telegram live) · **Design resume:** `docs/KAVACH_ATO_CONFIGURATION_DESIGN.md`  
**Last updated:** 2026-07-15

---

## Pending answers — none

ATO Configuration / Quick Tune operator Q&A complete (Q79–Q98). **Coded** 2026-07-15 — see `ato_configuration_wizard.py`.

---

## Locked / skipped (Q79–Q98) — 2026-07-15

| # | Answer | Notes |
|---|--------|-------|
| Q79 | **A** | Retrace SELL = registered ATO lots only; never sell excess manual qty |
| Q80 | **A** | Partial manual ignored (Q73) + breach on → BUY remainder book-first |
| Q81 | **A** | Exact manual buy = adopt holding / exit-only; no second BUY on breach |
| Q82 | **A** | Add lots while holding → ignore excess; exit scope stays registered |
| Q83 | **C** | Quick Tune = **buffers only** in v1; lots/strikes still need Complete → register |
| Q84 | **A** | Quick Tune v1 = buffers only (entry + exit), both sides |
| Q85 | **A** | Quick Tune while holding allowed; new buffer applies next tick |
| Q86 | **skipped** | N/A Quick Tune v1 (Q83 C / Q84 A); revisit if Complete mid-hold lot ↑ |
| Q87 | **A** | Lots ↓ while holding → registered smaller; ignore broker excess (Q72) |
| Q88 | **skipped** | N/A Quick Tune v1 (buffers only); strikes stay Complete → register |
| Q89 | **A** | Entry buffer while holding: recalc only; new buffer → next cycle after retrace |
| Q90 | **C** | Invoke via `/ato_tune` **and** `/ato_status` buttons |
| Q91 | **A** | Menu label = **ATO Configuration** |
| Q92 | **C** | Side pick: Both → CE only | PE only | both | Cancel |
| Q93 | **A** | Every step: current value + **[ Keep current ]** |
| Q94 | **C** | v1 order = **Entry → Exit** (buffers only; no strike/lots in Quick Tune) |
| Q95 | **C** | Confirm = summary + **warnings** + Apply |
| Q96 | **C** | Strike UI (future/Complete): register keyboards + **highlight current** |
| Q97 | **A** | Both sides: all CE then all PE → one summary |
| Q98 | **B** | Not armed: tap → “Register first” + point to `/register` |

---

## Locked answers (Q71–Q78)

| # | Answer | Notes |
|---|--------|-------|
| Q71 | **A** | 15:15 IST → stop monitoring only; open legs stay on Dhan *(recommended — not explicitly stated)* |
| Q72 | **A** | 26A manual buy **more** lots → algo scope = **registered ATO lots only**; warn excess outside scope |
| Q73 | **C** | 26A manual buy **fewer** lots → **ignore** partial manual; at breach BUY **registered** lots (book-first) |
| Q74 | **A** | Side halt stays until operator `/resume` — book self-heal does not auto-clear |
| Q75 | **A** | Resume clears global pause **and** resumable side halt(s); re-evaluate (Q55) |
| Q76 | **A** | Do not count soft-cap breaches while paused / not monitoring |
| Q77 | **A** | Allow Batman Complete while paused / side halted |
| Q78 | **A** | One side order-fail → halt that side only; other side continues (Q28) |

---

## Locked answers (Q63–Q70)

| # | Answer | Notes |
|---|--------|-------|
| Q63 | **C** | Auto-resume at 09:25 **only** for feed-owned pauses; operator Pause stays manual |
| Q64 | **A** | Circuit freeze = same as stale feed — pause; Resume when tradeable |
| Q65 | **A** | 26B partial book at breach → retry remainder (up to 3×); do not adopt as full |
| Q66 | **A** | Stray leg closed → no action; continue monitoring |
| Q67 | **A** | Gate 5 preset +1000 + 1 lot → **no** SARANSH economy tag (Q49 A) |
| Q68 | **A** | CE-only monitor → ignore stray PE on Dhan |
| Q69 | **A** | Wizard cancel after Complete → safe idle |
| Q70 | **A** | Complete with open ATO legs → warn + checklist only; do not block |

---

## Locked answers (Q47–Q54)

| # | Answer | Notes |
|---|--------|-------|
| Q47 | **A** | Halt blocks everything on that side until Complete → re-register |
| Q48 | **A** | 3 fast book retries (idempotency) |
| Q49 | **A** | SARANSH tag **custom protect strike only** — presets normal |
| Q50 | **C+** | Ignore stray/wrong-strike legs — no pause; monitor registered protect only |
| Q51 | **A** | Pause side on manual full exit of registered protect |
| Q52 | **A** | Resume monitors registered strike only; never touch wrong leg |
| Q53 | **A** | Pause **ALL** ATO + JAGRAN on unreadable position book |
| Q54 | **A** | Implement full §7 manual-leg sync matrix next |

---

## Locked answers (Q55–Q62)

| # | Answer | Notes |
|---|--------|-------|
| Q55 | **C** | `/resume` clears **manual-intervention side halt(s)**; re-evaluate from current NIFTY; other side unchanged |
| Q56 | **A** | After manual-exit pause + resume with breach on → **BUY immediately** if protect **not** already at broker (book-first) |
| Q57 | **A** | 26B — adopt full book; no duplicate order |
| Q58 | **C** | SARANSH: deployment header **+** dedicated ATO/economy section (custom protect only, Q49 A) |
| Q59 | **A** | Orphan legs at Confirm → **warn only**; allow register (Q40) |
| Q60 | **B** | 26A adopt qty mismatch → exit **registered ATO qty only**; warn |
| Q61 | **B** | Non-lot partial sell **cannot happen** on Dhan (lot size 65); if odd qty seen → ignore until whole lots (edge guard) |
| Q62 | **Custom** | Position read: **retry up to 3×** per poll; still unreadable → pause ALL + JAGRAN; recovery on retry → JAGRAN info alert, **continue** (no manual Resume for transient blip) |

## QUESTION #47

**Area:**  
Batman qty drift vs retrace exit

**Scenario:**  
CE side armed. Operator manually closes part of a **Batman** leg (not protect) on Dhan. Broker qty < managed qty. Side halts. Spot later retraces — should KAVACH still SELL the protect leg?

**Options:**  
A. Halt blocks everything on that side — no retrace until Complete → re-register  
B. Halt blocks new BUY only — retrace SELL still allowed if protect leg is open  
C. Halt blocks retrace too — but auto-clear halt once broker qty matches managed again  
D. Custom  

**Recommended:**  
A *(aligns with Q41)*

**Operator answer:** **A**

---

## QUESTION #48

**Area:**  
Order placement / book validation

**Scenario:**  
ATO BUY fires. Dhan accepts order but local book shows 0 qty for 1–2 poll ticks (lag). Current code retries up to 3× immediately.

**Options:**  
A. Keep 3 fast retries — idempotency prevents duplicates  
B. Add short settle wait (e.g. 1–2 s) between retries before re-ordering  
C. Trust order ID on success if book is None/unreadable; retry only on explicit mismatch  
D. Custom  

**Recommended:**  
A for Phase 1 *(Q8/Q12 locked: book-first + 3 retries)*

**Operator answer:** **A**

---

## QUESTION #49

**Area:**  
SARANSH economy profile tag

**Scenario:**  
Operator uses CE preset **+1000** (far OTM) with ATO lots = 1. Economy chop test — should SARANSH show **Custom ATO / economy profile**?

**Options:**  
A. Tag **custom protect only** (typed strike) — presets are “normal”  
B. Tag **any** far-from-auto protect (preset +500/+1000/−500 or custom)  
C. Tag when ATO lots < managed lots **or** custom strike **or** preset offset ≥ 500  
D. Custom  

**Recommended:**  
C *(Q25 intent — economy = cheap chop test, not only free-text custom)*

**Operator answer:** **A** — keep SARANSH simple; custom typed strike only

---

## QUESTION #50

**Area:**  
Manual leg — wrong strike / stray positions (26C)

**Scenario:**  
Armed for protect 26,000 CE. Operator manually buys 26,500 CE on Dhan (wrong strike) or other directional legs. Algo idle on CE.

**Options:**  
A. Pause **CE side** + warn + JAGRAN — ignore wrong leg; never touch it  
B. Pause whole algo (both sides)  
C. Warn only — keep monitoring registered strike  
D. Custom  

**Recommended:**  
A *(was locked as **26C** — superseded by operator 2026-06-21)*

**Operator answer:** **C+** — **no special action**; ignore background noise; monitor registered protect only; operator handles stray legs manually

---

## QUESTION #51

**Area:**  
Manual leg — full exit while holding (26D / 31)

**Scenario:**  
ATO active (holding 2 lots 26,000 CE). Operator manually SELLs all 2 lots on Dhan. Algo still thinks `ce_triggered=True`.

**Options:**  
A. Pause **that side** + warn — operator must Resume or Complete  
B. Auto-adopt flat book → reset triggered=False; continue monitoring  
C. Pause side + auto-reset flags when book shows 0 protect qty  
D. Custom  

**Recommended:**  
A *(locked as **26D** / **31** in §7)*

**Operator answer:** **A**

---

## QUESTION #52

**Area:**  
Resume after wrong-strike pause (34A)

**Scenario:**  
CE paused because wrong-strike manual leg exists. Operator runs `/resume`. Wrong leg still on Dhan.

**Options:**  
A. Resume monitoring **registered protect only** — warn; never touch wrong leg  
B. Block Resume until wrong leg closed manually  
C. Resume + attempt to close wrong leg automatically  
D. Custom  

**Recommended:**  
A *(locked as **34A** in §7)*

**Operator answer:** **A** *(applies when side paused for other reasons; Q50 wrong-strike does not pause)*

---

## QUESTION #53

**Area:**  
Position book unreadable (Q33)

**Scenario:**  
`get_positions()` fails or returns unreadable during breach check. CE side was about to fire.

**Options:**  
A. Pause **ALL** ATO (CE + PE) + JAGRAN  
B. Pause only the side that was acting  
C. Skip one tick; retry next poll — pause only after N consecutive failures  
D. Custom  

**Recommended:**  
A *(locked as Q33)*

**Operator answer:** **A**

---

## QUESTION #54

**Area:**  
Implementation priority (next coding chunk)

**Scenario:**  
Core ATO engine done (soft cap, per-side halt, register gate, presets). What ships next?

**Options:**  
A. Full manual-leg sync matrix (§7: 26A–26D, 31, 34A–B)  
B. SARANSH economy tag UI + deployment display  
C. Wrong-strike detection (26C) only — smallest slice  
D. Custom order (operator specifies)  

**Recommended:**  
A *(largest behavioural gap vs operator bible)*

**Operator answer:** **A**

---

## Already locked — reference only (do not re-ask)

### Manual-leg matrix §7 (updated 2026-06-21)

| ID | Scenario | Locked decision |
|----|----------|-----------------|
| 26A | Idle; manual buy correct protect | Adopt + warn → holding, exit-only |
| 26B | Breach; you + algo buy; book full | Filled — no retry |
| 26C | Manual buy wrong strike / stray legs | **Ignore** — monitor registered protect only (Q50) |
| 26D | Holding; manual sell all registered protect | Pause affected side + warn |
| 31 | Holding; manual sell partial registered protect | Pause affected side + warn |
| 34A | Side paused; resume with stray leg on book | Resume + warn; registered strike only |
| 34B | Stray leg closed; resume | Normal armed behaviour |
| 40 | Orphan protect after new register | Warn at confirm; ignore for algo |

Full index: `docs/KAVACH_ATO_OPERATOR_RULES.md` §14.

*Q63–Q70 below — answer by voice. Q1–Q62 locked. See `docs/KAVACH_Tuesday_RESUME.md`.*

---

## QUESTION #63

**Area:**  
DRISHTI feed recovery — auto-resume at monitoring start

**Scenario:**  
Monday 09:20. Algo paused overnight because NIFTY cache was stale. 09:25 monitoring start. DRISHTI feed is healthy again.

**Options:**  
A. **Auto-resume** ATO at 09:25 if feed healthy (no operator Resume tap)  
B. **Always manual** Resume — operator must tap every time after stale pause  
C. Auto-resume only for **feed-owned** pause reasons; **operator Pause** stays manual  
D. Custom  

**Recommended:**  
C *(feed-owned recovery yes; operator Pause stays manual)*

**Operator answer:** **C**

---

## QUESTION #64

**Area:**  
Circuit freeze / untradeable spot (Q23)

**Scenario:**  
NIFTY hits exchange circuit band. Spot price stale or untradeable. ATO was monitoring.

**Options:**  
A. **Same as stale feed** — pause ATO; operator Resume when tradeable again  
B. Keep monitoring but block new orders only  
C. Pause only the breached side  
D. Custom  

**Recommended:**  
A *(locked intent in bible Q23)*

**Operator answer:** **A**

---

## QUESTION #65

**Area:**  
26B edge — partial book at breach

**Scenario:**  
CE breach. You and algo both buy. Next poll: broker shows **1 lot** (65 qty) but registered ATO = **2 lots** (130).

**Options:**  
A. **Retry** remaining qty per order rules (up to 3×); do not adopt as “full”  
B. Adopt partial as holding; exit-only for 65; warn mismatch  
C. Pause CE side until book shows full 130  
D. Custom  

**Recommended:**  
A *(consistent with Q8/Q12 whole-lot validation)*

**Operator answer:** **A**

---

## QUESTION #66

**Area:**  
34B — stray leg closed; side was never paused (Q50)

**Scenario:**  
Wrong-strike leg was on Dhan (ignored). Operator closes it manually. Registered protect unchanged. Algo was never paused for stray leg.

**Options:**  
A. **No action** — continue normal armed monitoring  
B. Force one-time state reset (triggered flags)  
C. Send KAVACH info “stray leg cleared” only  
D. Custom  

**Recommended:**  
A *(Q50 — stray legs are background noise)*

**Operator answer:** **A**

---

## QUESTION #67

**Area:**  
Gate 5 economy — SARANSH tag (Q49 A confirmation)

**Scenario:**  
Register CE preset **+1000**, ATO lots = **1**, managed lots = **2**. Economy chop test.

**Options:**  
A. **No** SARANSH economy tag — preset is normal per Q49 A  
B. Tag anyway because far OTM + partial lots  
C. Tag only in KAVACH Confirm warn, not SARANSH  
D. Custom  

**Recommended:**  
A *(Q49 A locked — custom typed strike only)*

**Operator answer:** **A**

---

## QUESTION #68

**Area:**  
CE-only monitor + stray PE on Dhan (Q46)

**Scenario:**  
`ato.manage_sides = ce`. Operator has unrelated **PE long** on Dhan from another strategy.

**Options:**  
A. **Ignore** PE completely — monitor registered CE protect only  
B. Warn once at register if any non-registered long exists  
C. Pause PE side (even though not monitored)  
D. Custom  

**Recommended:**  
A *(Q46 locked)*

**Operator answer:** **A**

---

## QUESTION #69

**Area:**  
Wizard cancel after Complete auto-start (Q42)

**Scenario:**  
Batman Complete OK → register wizard auto-opens → operator taps **Cancel**.

**Options:**  
A. **Safe idle** — no armed deployment; run `/register` again when ready  
B. Partial state saved — warn and block trading  
C. Auto-reopen wizard until Confirm  
D. Custom  

**Recommended:**  
A *(Q42 locked)*

**Operator answer:** **A**

---

## QUESTION #70

**Area:**  
Batman Complete with open ATO protect legs still on Dhan

**Scenario:**  
Complete lists 26,000 CE protect still open. Operator confirms Complete anyway.

**Options:**  
A. **Warn + checklist only** — does not block Complete; operator closes manually before next register  
B. Block Complete until all listed ATO legs flat  
C. Auto-close protect legs (never)  
D. Custom  

**Recommended:**  
A *(bible §3 — list + warn, do not block)*

**Operator answer:** **A**

---

## QUESTION #71

**Area:**  
Daily **15:15 IST** ATO stop (bible Q10 — not wired in code today)

**Scenario:**  
15:15 IST. CE side **holding** 2 lots protect (130 qty). Breach/retrace loop was active all day.

**Options:**  
A. **Stop monitoring only** — no new BUY/SELL; open legs stay on Dhan until you manage manually or next session  
B. Stop monitoring **and** auto-**SELL** all open ATO protect legs at 15:15  
C. **Pause** algo globally at 15:15 (same as operator Pause) — `/resume` next day if still armed  
D. Custom  

**Recommended:**  
A *(operator owns exits; no surprise orders at cutoff)*

**Operator answer:** **A** *(recommended — operator did not state explicitly)*

---

## QUESTION #72

**Area:**  
26A mid-session — manual buy **more** lots than registered ATO (idle, before breach)

**Scenario:**  
Registered ATO = **2 lots** (130). You manually buy **3 lots** (195) at the **correct** protect strike before breach.

**Options:**  
A. Adopt **registered 2 lots** for algo; warn that 1 lot is outside ATO scope  
B. Adopt **full 3 lots** — algo manages all broker qty  
C. Pause CE side until you reduce to registered size  
D. Custom  

**Recommended:**  
A *(mirror register-time Q22 — excess outside scope)*

**Operator answer:** **A** — registered ATO lots only; excess manual qty out of algo scope (warn)

---

## QUESTION #73

**Area:**  
26A mid-session — manual buy **fewer** lots than registered (idle)

**Scenario:**  
Registered ATO = **2 lots**. You manually buy **1 lot** at correct protect strike before breach.

**Options:**  
A. Adopt **broker 1 lot** — holding exit-only for 65; warn partial  
B. Pause CE — must match registered 2 lots before monitoring continues  
C. Ignore manual buy — wait for algo breach BUY for full 2 lots  
D. Custom  

**Recommended:**  
A *(mirror register-time Q21)*

**Operator answer:** **C** — ignore partial manual buy; breach path buys registered lots only

---

## QUESTION #74

**Area:**  
Side halt **without** operator `/resume` — book “self-heals”

**Scenario:**  
CE paused after **26D** (you sold all protect manually). Later you **buy back** full 2 lots on Dhan yourself. You do **not** tap `/resume`. Spot is still breached.

**Options:**  
A. Side **stays halted** until you tap `/resume` (algo does nothing even if book looks full)  
B. Auto-clear halt when broker qty matches registered ATO qty again  
C. Auto-clear halt **and** immediately evaluate breach/retrace from current spot  
D. Custom  

**Recommended:**  
A *(operator must explicitly Resume after manual intervention)*

**Operator answer:** **A**

---

## QUESTION #75

**Area:**  
**Operator Pause** vs **per-side halt** (stacking)

**Scenario:**  
CE side halted (order fail after 3 retries). PE still running. You tap **Pause** (global). Later you tap **Resume**.

**Options:**  
A. **Resume** clears global pause **and** CE side halt → CE re-evaluates from current spot (Q55)  
B. Resume clears global pause only — CE side halt **stays** until separate fix/Complete  
C. Resume blocked while any side halt active — must Complete first  
D. Custom  

**Recommended:**  
A *(Resume is the operator ack after fixing the side)*

**Operator answer:** **A**

---

## QUESTION #76

**Area:**  
Soft-cap chop counter while paused

**Scenario:**  
Algo **paused** (feed stale or operator Pause). NIFTY keeps chopping through CE sell + buffer. No orders fire.

**Options:**  
A. **Do not count** breaches toward soft-cap while paused / not monitoring  
B. **Count** breach alerts anyway (chop exposure even when idle)  
C. Count only for **monitor-only (0 lots)** sides; not when fully paused  
D. Custom  

**Recommended:**  
A *(no monitoring → no cycle economics)*

**Operator answer:** **A**

---

## QUESTION #77

**Area:**  
**Batman Complete** while algo paused or side halted

**Scenario:**  
CE side halted (Batman qty drift). Algo globally paused. You want new settings mid-week.

**Options:**  
A. **Allow Complete** — cleanup/verify/archive proceeds; side halt cleared as part of state reset  
B. Block Complete until all halts cleared and algo running  
C. Allow Complete but **block** auto-wizard until manual `/resume` once  
D. Custom  

**Recommended:**  
A *(Complete is lifecycle; Q24 path should always work)*

**Operator answer:** **A**

---

## QUESTION #78

**Area:**  
**Both sides breach** same poll — CE order path fails

**Scenario:**  
CE and PE breach on same tick. CE BUY fails after 3 retries → CE side halt + JAGRAN. PE BUY succeeds and is holding.

**Options:**  
A. **CE halted, PE continues** independently (Q28) — no global pause  
B. **Pause ALL** ATO if either side order-fails  
C. Pause ALL only if **both** sides fail  
D. Custom  

**Recommended:**  
A

**Operator answer:** **A**

---

## QUESTION #79

**Area:**  
26A + excess manual qty — **retrace SELL** scope (Q60 + Q72)

**Scenario:**  
Registered ATO = **2 lots**. You manually bought **3 lots** at correct protect (26A adopt). Spot retraces. Broker shows 195 qty.

**Options:**  
A. SELL **registered 2 lots only** (130 qty); warn — **never** SELL the extra 65  
B. SELL full broker 195 qty  
C. Pause side — operator must reduce book to registered size first  
D. Custom  

**Recommended:**  
A *(Q60 + Q72 — registered ATO qty is the only managed exit)*

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #80

**Area:**  
26A **ignore partial** (Q73 C) + breach **already on**

**Scenario:**  
Registered ATO = **2 lots**. You manually buy **1 lot** at correct strike (ignored per Q73). Spot is **already breached** (above CE sell + buffer).

**Options:**  
A. On next eval: if registered protect **not fully** at broker → **BUY remainder** (1 lot) per book-first; ignore the manual 1 lot as “already there” for qty math  
B. SELL the manual 1 lot first, then BUY 2 fresh lots  
C. Pause side — operator must fix book manually  
D. Custom  

**Recommended:**  
A *(book-first: need 130 total for registered scope; 65 present → buy 65 more)*

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #81

**Area:**  
26A manual buy **exact** registered lots (idle)

**Scenario:**  
Registered ATO = **2 lots**. You manually buy **exactly 2 lots** at correct protect before breach.

**Options:**  
A. **Adopt** → holding, exit-only; **no second BUY** on breach (26A)  
B. Ignore manual buy — still BUY 2 lots on breach  
C. Pause side — duplicate risk  
D. Custom  

**Recommended:**  
A *(standard 26A)*

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #82

**Area:**  
**Holding** (algo active) — operator **adds** lots on Dhan above registered

**Scenario:**  
Algo holding 2 lots (130). You manually buy **1 more lot** on Dhan (195 total). Registered ATO still 2 lots.

**Options:**  
A. **Ignore** extra lot — retrace SELL **registered 2 lots only** (Q60); warn excess on book  
B. Adopt 3 lots — algo now manages 195  
C. Pause CE side until book back to 130  
D. Custom  

**Recommended:**  
A *(same principle as Q72 — registered scope only)*

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #83

**Area:**  
Quick Tune vs Q24 Complete path

**Scenario:**  
Tuesday 11:00. Batman armed, CE holding 2 lots protect. You want **exit buffer 5 → 10** only.

**Options:**  
A. **Quick Tune** — patch deployment; **no** Complete; short confirm  
B. Still **Complete → full register** for any mid-week change (keep Q24)  
C. Quick Tune for **buffers only**; lots/strikes still need Complete → register  
D. Custom  

**Operator answer:** **C** (2026-07-15) — Quick Tune buffers only in Phase 1 v1; lots/strikes need Complete → register

---

## QUESTION #84

**Area:**  
What Quick Tune covers in **v1**

**Options:**  
A. **Buffers only** (entry + exit) — both sides  
B. Buffers + **ATO lots** (not strikes)  
C. Buffers + lots + **protect strike**  
D. Custom list  

**Recommended:**  
B–C *(operator intent: strike + lots + buffers)*

**Operator answer:** **A** (2026-07-15) — buffers only; consistent with Q83 C

---

## QUESTION #85

**Area:**  
Quick Tune while **holding** protect

**Scenario:**  
CE **holding** 2 lots. You change exit buffer via ATO Configuration.

**Options:**  
A. **Allowed** — apply immediately; new buffer on next tick  
B. Allowed only when **flat** on that side  
C. Auto-**pause** side during tune → Resume after confirm  
D. Custom  

**Recommended:**  
A for buffers; **C** for safety while holding

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #86

**Area:**  
ATO lots **increase** while holding (2 → 3)

**Options:**  
A. Update scope to 3; **BUY 1 lot now** if breach on (book-first)  
B. Update to 3; **wait** for next breach cycle after flat  
C. Block increase while holding  
D. Custom  

**Recommended:**  
A

**Operator answer:** **skipped** (2026-07-15) — N/A Quick Tune v1 (Q83 C / Q84 A); revisit if Complete mid-hold lot ↑ needed

---

## QUESTION #87

**Area:**  
ATO lots **decrease** while holding (3 → 2, broker 195)

**Options:**  
A. Registered = 2; **ignore** extra 65 (Q72); SELL 130 only  
B. Block until you manually sell extra  
C. Pause side until broker = 130  
D. Custom  

**Recommended:**  
A

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #88

**Area:**  
**Protect strike** change via ATO Configuration

**Scenario:**  
26,000 CE → 26,500 CE; old leg still on Dhan.

**Options:**  
A. **Block** while old protect open — flat first  
B. Allow — old leg **orphan** (warn); manage new strike only  
C. **Never** in Quick Tune — strikes only at full register  
D. Custom  

**Recommended:**  
C for v1; **B** if mid-session strike tune required

**Operator answer:** **skipped** (2026-07-15) — N/A Quick Tune v1 (buffers only); strikes via Complete → register only

---

## QUESTION #89

**Area:**  
Entry buffer change while **already breached** and holding

**Options:**  
A. **Recalc only** — stay holding; new buffer affects **next** cycle after retrace  
B. “No longer breached” → **SELL** protect  
C. Block entry-buffer edits while holding  
D. Custom  

**Recommended:**  
A

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #90

**Area:**  
How to invoke Quick Tune / ATO Configuration

**Options:**  
A. Command **`/ato_tune`** only  
B. Inline buttons on **`/ato_status`** only  
C. **Both** command + status buttons  
D. Custom  

**Recommended:**  
C

**Operator answer:** **C** (2026-07-15)

---

## QUESTION #91

**Area:**  
Main menu label

**Options:**  
A. **ATO Configuration**  
B. **Tune ATO**  
C. **Change ATO Settings**  
D. Custom  

**Recommended:**  
A

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #92

**Area:**  
Screen 1 — side selection UX

**Options:**  
A. **CE · PE · Both** (no Skip on screen 1)  
B. “Tune CE?” Yes / Skip, then PE  
C. **Both** → sub-menu: CE only | PE only | both | Cancel  
D. Custom  

**Recommended:**  
C

**Operator answer:** **C** (2026-07-15)

---

## QUESTION #93

**Area:**  
Unchanged values — speed UX

**Options:**  
A. **Current value** + **[ Keep current ]** on every step  
B. Ask all 4 fresh every time  
C. Pick **which fields** to change first, then only those questions  
D. Custom  

**Recommended:**  
A *(C later for max speed)*

**Operator answer:** **A** (2026-07-15)

---

## QUESTION #94

**Area:**  
Question order per side

**Options:**  
A. **Strike → Lots → Entry → Exit** *(operator stated)*  
B. **Lots → Strike → Entry → Exit** *(matches register wizard)*  
C. Custom order  
D. Custom  

**Recommended:**  
B for consistency — **operator preference strike-first pending**

**Operator answer:** **C** (2026-07-15) — v1 Quick Tune = **Entry → Exit** only (buffers; Q83 C / Q84 A)

---

## QUESTION #95

**Area:**  
Confirm before Apply

**Options:**  
A. Summary old → new + **[ Apply ] [ Cancel ]**  
B. Apply immediately after last question  
C. Summary + **warnings** + Apply  
D. Custom  

**Recommended:**  
C

**Operator answer:** **C** (2026-07-15)

---

## QUESTION #96

**Area:**  
Strike step UI

**Options:**  
A. Same keyboards as register (Auto, presets, Custom)  
B. Current strike + Custom text only  
C. Same as A + **highlight current**  
D. Custom  

**Recommended:**  
C

**Operator answer:** **C** (2026-07-15) — for future widen / Complete path (not in Quick Tune v1)

---

## QUESTION #97

**Area:**  
Both sides — question order

**Options:**  
A. All **CE (4)** then all **PE (4)** → one summary  
B. Alternate CE/PE per field  
C. Operator picks side order  
D. Custom  

**Recommended:**  
A

**Operator answer:** **A** (2026-07-15) — v1: all CE buffers then all PE buffers → one summary

---

## QUESTION #98

**Area:**  
Menu when not armed

**Options:**  
A. Button hidden  
B. Tap → “Register first” + point to `/register`  
C. Same as B + start register wizard  
D. Custom  

**Recommended:**  
B

**Operator answer:** **B** (2026-07-15)
