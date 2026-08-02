# Phase 1 robot launcher (Windows)



Authoritative operator guide for starting, stopping, and checking **DRISHTI**, **KAVACH**, and **JAGRAN** on the dev laptop.  

Architecture lock: `CONTEXT.md` §3.1.



Last updated: 2026-06-12



---



## Quick reference



| Task | File (double-click) |

|------|---------------------|

| **Start all** Phase 1 bots | `Execution\Start Bots\Phase 1 Start All Robots.bat` (supervisor — recommended) |
| **Start all** (legacy .bat windows) | `.venv\Scripts\python.exe scripts\phase1_start_all.py --legacy-bats` |
| **Supervisor start** | `Execution\Start Bots\Supervisor Start All.bat` |
| **Stop all** Phase 1 bots | `Execution\Stop Bots\Phase 1 Stop All Robots.bat` |
| **Supervisor stop** | `Execution\Stop Bots\Supervisor Stop All.bat` |

| **Status** (all bots) | `Execution\Start Bots\Show Bot Status.bat` or `Execution\Stop Bots\Show Bot Status.bat` |

| **Reconcile** (stuck locks) | `Execution\Start Bots\Reconcile Bots.bat` |

| Start one bot | `Execution\Start Bots\start <Bot>.bat` |

| Stop one bot | `Execution\Stop Bots\stop <Bot>.bat` |



Agent/scripts: `scripts\phase1_start_all.py`, `scripts\phase1_stop_all.py`, `scripts\bot_status.py all`, `scripts\reconcile_bots.py`.

**Lifecycle architecture:** `docs/BOT_LIFECYCLE_ARCHITECTURE.md` · handoff: `NEW_CHAT_HANDOFF.md`



---



## Operator rules (non-negotiable)



1. **Start** and **stop** only via `.bat` files in `Execution\Start Bots\` and `Execution\Stop Bots\`.

2. **Do not** close a “Bot - Running” window with the **X** button — use the matching **stop** `.bat` or **Phase 1 Stop All Robots.bat**.

3. **Do not** run `python run_*.py` by hand for normal operation.

4. After any stop, confirm with **Show Bot Status** → every bot must show **STOPPED**.



---



## Phase 1 Stop All Robots.bat



Location: `Execution\Stop Bots\Phase 1 Stop All Robots.bat`  

Engine: `scripts\phase1_stop_all.py`



| Behaviour | Detail |

|-----------|--------|

| Retries | Up to **5** full stop passes (DRISHTI → KAVACH → JAGRAN) |

| Verify | Each pass checks all bots **STOPPED** via `classify_bot` |

| Success | Window **auto-closes after 5 seconds** (interactive mode) |

| Failure | **Windows error popup** + console stays open + log under `launchers/stop_all/` |

| Silent | `Phase 1 Stop All Robots.bat silent` — used by Start All (no 5s close; popup still on hard failure) |



**Logs (daily, IST):**



```

logs/runtime/YYYY-MM/YYYY-MM-DD/launchers/stop_all/logs/all.log

logs/runtime/YYYY-MM/YYYY-MM-DD/launchers/stop_all/errors/all_errors.log

```



Line format matches robot logs (`LOGGING_LAYOUT.md`).



---



## Phase 1 Start All Robots.bat



Location: `Execution\Start Bots\Phase 1 Start All Robots.bat`  

Engine: `scripts\phase1_start_all.py`



| Step | Detail |

|------|--------|

| 1 | Stop All (silent, 5 retries) |

| 2 | Open 3 CMD windows: DRISHTI → wait 12s → KAVACH → wait 5s → JAGRAN |

| 3 | Poll up to **2 minutes** (every 5s) until all report **RUNNING** |

| Success | Message in console + launcher window **auto-closes after 5 seconds** |

| Failure | **Windows error popup** (which bots not RUNNING) + pause + log |



Startup can take a while — the script waits the full 2 minutes before failing.



**Logs (daily, IST):**



```

logs/runtime/YYYY-MM/YYYY-MM-DD/launchers/start_all/logs/all.log

logs/runtime/YYYY-MM/YYYY-MM-DD/launchers/start_all/errors/all_errors.log

```



Optional: `Phase 1 Start All Robots.bat force` — passes `force` to each start `.bat`.



---



## Show Bot Status.bat



- `Execution\Start Bots\Show Bot Status.bat` (canonical)

- `Execution\Stop Bots\Show Bot Status.bat` (delegates to Start Bots)



---



## Dev testing workflow



1. **Stop All** → auto-close on success; check `launchers/stop_all/logs/all.log` if fail.

2. **Start All** → wait for verification; three bot windows; check `launchers/start_all/logs/all.log` on timeout.

3. **Show Bot Status** anytime.

4. If Start All fails → **Reconcile Bots** → Start All again.

5. End session: **Stop All** (not X on bot windows).



---



## Dev laptop vs Cursor agent terminals



This repo targets a **Windows dev laptop**, not a VPS. Two different ways to start bots exist; mixing them causes duplicate processes and file-lock errors on `data/nifty_ltp_cache.json` (WinError 5).



| Who starts bots | How | When to use |

|-----------------|-----|-------------|

| **You (operator)** | `Execution\Start Bots\` / `Stop Bots\` `.bat` files | **Daily trading and Telegram testing** — one visible CMD window per bot |

| **Cursor agent** | Integrated terminal: `.venv\Scripts\python.exe run_kavach.py` etc. | **Debugging only** — agent can tail logs in the same session; stop via Stop `.bat` or `scripts\stop_*.py` when done |



**Rules:**



1. Do **not** run Start All `.bat` and also start the same bot from a Cursor terminal — you get two KAVACH/DRISHTI instances (429 on LTP, stale cache, broken menus).

2. **Show Bot Status** may list **two PIDs** per bot; that is usually **one instance** (CMD parent + Python child). Worry only if status shows **more than one launcher tree** or a WARNING about duplicate PIDs.

3. DRISHTI writes `nifty_ltp_cache.json` every ~2s; KAVACH reads it. Locks are retried in code; still prefer a **single DRISHTI** process.

4. After an agent debug session, run **Phase 1 Stop All Robots.bat** (or let the agent run `scripts\phase1_stop_all.py`) before you start bots again with `.bat`.



**Can you run bots in Cursor for monitoring?** Yes: open a **new terminal** in Cursor, `cd` to the repo, run e.g. `.venv\Scripts\python.exe run_kavach.py` — the agent can read `logs/runtime/...` in parallel. For your normal workflow, keep using `.bat` so windows stay visible and `BATMAN_LAUNCHED_VIA_BAT=1` is set; use Cursor runs only when you and the agent are actively debugging together.



---



## Implementation map



| Component | Path |

|-----------|------|

| Bulk stop orchestrator | `scripts/phase1_stop_all.py` |

| Bulk start orchestrator | `scripts/phase1_start_all.py` |

| Launcher daily logs | `core/launcher_session_log.py` |

| Failure popup | `core/win_popup.py` |

| PID + lock classification | `core/bot_process_status.py` |

| Status CLI | `scripts/bot_status.py` |



---



## Related docs



- `CONTEXT.md` §3.1–3.2  

- `INCIDENT_TRACKER.md` — domain error CSVs (`start_all`, `stop_all`, bots)  

- `LOGGING_LAYOUT.md` — includes `launchers/stop_all` and `launchers/start_all`  

- `ROBOT_DEBUG_PROTOCOL.md`  


