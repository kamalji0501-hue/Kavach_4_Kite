# Rahul → Kamalji handover (detailed)

**Date:** 2026-08-06  
**Status:** Rahul’s architecture/restructuring on this track is **DONE**.  
**Owner from now:** Kamalji (+ Cursor AI)  
**Primary start file:** [`context/KAMALJI_HANDOFF.md`](../context/KAMALJI_HANDOFF.md)

---

## Executive summary

Rahul restructured the Batman sandbox so that:

1. Code stays lean; heavy data lives under `Trading_Runtime_Rahul`.  
2. Place Order is a **backend** execution capability (paper via Order Manager).  
3. Register asks **Paper vs Live** first.  
4. Deep money-safe logging and tick CSV exist for testing.  
5. Dhan PIN/TOTP is available as a **capability** (secrets-root mapped), without forcing Telegram UX changes.  
6. Everything required is on GitHub branch **`rahul`**.

Kamalji continues as the Algo / options-selling flow expert on the **same VPS**, same `rahul_Changes` folder.

---

## Locked paths

| Role | Absolute path |
|------|----------------|
| Code under test | `/home/ubuntu/rahul_Changes` |
| Runtime | `/home/ubuntu/Trading_Runtime_Rahul` |
| Secrets | `/home/ubuntu/Trading_Runtime_Rahul/Credentials` |
| Kamalji baseline code | `/home/ubuntu/batman-algo` |
| Kamalji baseline runtime | `/home/ubuntu/Trading_Runtime` |
| Place Order package | `/home/ubuntu/place-order-bot` |
| Git branch | `rahul` on `batman-algo` GitHub repo |

---

## Delivered capabilities (checklist)

- [x] Runtime split / release layout docs  
- [x] Order Manager + paper punch path  
- [x] Live path preserves broker punch  
- [x] Paper/Live register wizard question  
- [x] Money audit JSONL  
- [x] ATO NIFTY CE/PE tick CSV  
- [x] Robot verify + hardening scripts  
- [x] Telegram credentials on secrets_root  
- [x] Dhan PIN/TOTP capability + MLG context  
- [x] Git history cleaned; handover commits on `rahul`  

---

## What Kamalji should NOT redo

- Re-deriving the runtime folder layout  
- Replacing Place Order backend with Telegram Q&A in the ATO loop  
- Mixing Rahul runtime with Kamalji `Trading_Runtime`  
- Committing credentials into git  

---

## What Kamalji / Cursor should do next

1. Paper end-to-end Telegram tests (friend OK) using `docs/EVIDENCE_CHECKLIST_TESTER.md`  
2. Product flow polish (messages, menus) — keep ATO math stable unless intentional  
3. Optional: enable PIN/TOTP in `Credentials/config/dhan.env` (see MLG context)  
4. Live only after explicit checklist  

---

## Cursor AI note

Kamalji is not primarily a Python developer. Cursor must:

- Explain changes in trading / flow language  
- Keep diffs focused  
- Update context docs when behaviour changes  
- Never confuse this tree with `batman-algo`  

See `context/CURSOR_AI_GUIDE_FOR_KAMALJI.md`.

---

## Thank you

Rahul: architect pass complete.  
Kamalji: the book is yours — build the Algo flow with confidence.
