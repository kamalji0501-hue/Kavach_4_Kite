# Cursor AI guide for Kamalji (non-Python operator)

You are the **product / options-flow owner**. Cursor is the **coder**. Use plain language.

## How to talk to Cursor

Good prompts:

- “Paper mode must never hit the exchange. Show me proof in logs after a test punch.”  
- “Add a clearer Register message for Paper vs Live — do not change ATO strike logic.”  
- “Bot won’t start — read logs under Trading_Runtime_Rahul and fix without touching batman-algo.”  
- “Document what you changed in context/ and push to branch rahul.”

Avoid:

- Asking Cursor to “rewrite everything”  
- Mixing `/home/ubuntu/batman-algo` and `/home/ubuntu/rahul_Changes` in one task  
- Pasting real PIN / TOTP / bot tokens into chat (use secrets files on disk)

## Every session — ask Cursor to

1. Read `context/KAMALJI_HANDOFF.md` first  
2. Confirm `pwd` / git branch is `rahul` under `rahul_Changes`  
3. After code changes: run `scripts/robot_verify_phase1.py` when order/register/logging touched  
4. Commit only when you ask; never commit Credentials  

## Safety phrases you can paste

```text
Work only in /home/ubuntu/rahul_Changes and Trading_Runtime_Rahul.
Do not modify batman-algo or Trading_Runtime unless I explicitly say so.
Do not change ATO/trading math unless I explicitly ask.
Do not commit secrets. Prefer observability and docs over risky refactors.
```

## When Cursor seems confused

Point it at:

1. `context/KAMALJI_HANDOFF.md`  
2. `docs/PATH_AND_RELEASE_LAYOUT.md`  
3. The specific topic doc (Paper/Live, credentials, tick CSV, etc.)

## Verify green before trusting a fix

```bash
cd /home/ubuntu/rahul_Changes
.venv/bin/python scripts/robot_verify_phase1.py
```

Expect: `ALL CHECKS PASSED`.
