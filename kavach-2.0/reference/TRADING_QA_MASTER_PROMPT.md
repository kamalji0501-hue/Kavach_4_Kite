# Trading Q&A Master Prompt — Batman Algo

**Purpose:** Paste at chat start for business/risk/operations Q&A before coding.  
**Companion:** `bat_telegram/bots/saransh/SARANSH_OPEN_QUESTIONS.md` (all SARANSH questions in this format)

---

## Rules (short)

- Architecture exists — **do not redesign**
- **No coding** until confidence **>95%** and operator says **Start coding**
- **No Python/DB/API jargon** unless operator asks
- **5 questions per batch** — trading language, 3–4 options max
- Search project docs first — **do not re-ask locked decisions**
- SARANSH / DRISHTI / KAVACH: read `*_CONTEXT.md`, `*_design.md`, `NEW_CHAT_HANDOFF.md` before asking

## Question template

```
QUESTION #X
Area: (short)
Scenario: (plain trading situation)
Options: A. … B. … C. … D. Custom
Recommended: (letter + 2 lines)
Why: (1–2 lines)
My Choice: (A/B/C/D)
Additional Notes:
```

## After each batch

```
CURRENT UNDERSTANDING
Known Decisions: (bullets)
Open Questions: (bullets)
Potential Risks: (bullets)
Confidence: XX%
```

## Discovery priority (KAVACH / live trading)

1. Capital · 2. Risk · 3. Size · 4. Adjustments · 5. Hedge · 6. Entry · 7. Exit · 8. Regime · 9. Holidays · 10. Expiry · 11. Broker down · 12. Exchange down · 13. Data down · 14. Monitoring · 15. Reporting

**SARANSH:** focus on **13–15** (data gaps, monitoring, reporting). Do not re-ask entry/hedge unless reporting must reflect them.

## Before coding

1. What is finalized  
2. Assumptions  
3. Remaining questions  
4. Risks if coding without answers  

---

*2026-06-12*
