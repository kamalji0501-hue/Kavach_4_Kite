# Batman v3 — Test Inventory
## Every test, grouped by domain, with status and what it proves.
## Last updated: 2026-04-04  |  Baseline: 129/129 ✅

Legend: ✅ passing · 🔲 planned · ❌ blocked (code not written yet)

---

## FILE: tests/test_core.py  (40 tests ✅)

### TestConfig (4)
| #   | Test                  | Proves                                                  |
| --- | --------------------- | ------------------------------------------------------- |
| 1   | test_dot_notation_get | `config.get("strategy.lot_size")` traverses nested dict |
| 2   | test_nested_get       | Deep 3-level key works                                  |
| 3   | test_default_value    | Missing key returns supplied default, not KeyError      |
| 4   | test_section          | `config.get("strategy")` returns the whole dict section |

### TestState (4)
| #   | Test                        | Proves                                                    |
| --- | --------------------------- | --------------------------------------------------------- |
| 5   | test_set_and_get            | `state.set("foo.bar", 42)` → `state.get("foo.bar") == 42` |
| 6   | test_persistence            | New StateManager at same path reads keys set by first     |
| 7   | test_reset                  | After reset: custom key gone, session_id regenerated      |
| 8   | test_default_on_missing_key | Returns default, no exception                             |

### TestEventBus (3)
| #   | Test                   | Proves                                              |
| --- | ---------------------- | --------------------------------------------------- |
| 9   | test_publish_subscribe | Subscriber callback fires on publish                |
| 10  | test_unsubscribe       | After unsubscribe, callback no longer fires         |
| 11  | test_history           | get_history() returns all published events in order |

### TestUtils (5)
| #   | Test                         | Proves                                         |
| --- | ---------------------------- | ---------------------------------------------- |
| 12  | test_round_to_strike         | 25234.6→25250, 25200→25200, 25224.9→25200      |
| 13  | test_center_line             | Same as round_to_strike for ATM use case       |
| 14  | test_calculate_strikes       | BUY is INSIDE (closer to ATM), SELL is outside |
| 15  | test_otm_count_from_distance | 300pts→6 strikes, 550pts→11 strikes            |
| 16  | test_fmt_rupees              | Formats with ₹ symbol, handles negatives       |

### TestEntryWindow (5)
| #   | Test                                                  | Proves                                  |
| --- | ----------------------------------------------------- | --------------------------------------- |
| 17  | test_normal_wednesday_is_entry                        | Non-holiday Wednesday is entry day      |
| 18  | test_thursday_is_not_entry_when_wednesday_is_fine     | Thursday skipped if Wed was normal      |
| 19  | test_holiday_wednesday_shifts_entry_to_thursday       | Dussehra 2026-10-21 → shifts to Thu     |
| 20  | test_friday_is_not_entry_even_after_holiday_wednesday | Only one shift allowed                  |
| 21  | test_extra_holidays_param_respected                   | extra_holidays param overrides calendar |

### TestOptionSymbolUtils (10)
| #   | Test                                          | Proves                                             |
| --- | --------------------------------------------- | -------------------------------------------------- |
| 22  | test_parse_valid_ce_symbol                    | NIFTY25APR23000CE → (NIFTY25APR, 23000, CE)        |
| 23  | test_parse_valid_pe_symbol                    | NIFTY25APR22000PE → (NIFTY25APR, 22000, PE)        |
| 24  | test_parse_different_expiry_month             | JAN expiry works same as APR                       |
| 25  | test_parse_invalid_symbol_returns_none_triple | INVALID → (None, None, None)                       |
| 26  | test_ato_symbols_same_expiry_as_legs          | ATO symbol carries exact expiry prefix of sell leg |
| 27  | test_ato_ce_strike_is_one_step_higher         | CE ATO = ce_sell + 50                              |
| 28  | test_ato_pe_strike_is_one_step_lower          | PE ATO = pe_sell − 50                              |
| 29  | test_ato_different_expiry_still_correct       | Works for any month/expiry                         |
| 30  | test_ato_symbols_cannot_mix_expiries          | Mismatched expiries → each ATO follows its own leg |
| 31  | test_ato_invalid_symbol_returns_none          | Invalid sell → None ATO symbol, 0 strike           |

### TestTokenStore (10)
| #   | Test                                    | Proves                                            |
| --- | --------------------------------------- | ------------------------------------------------- |
| 32  | test_save_and_load_roundtrip            | save("token") → load() == "token"                 |
| 33  | test_absent_token_returns_none          | No file → (None, None) from load()                |
| 34  | test_fresh_token_not_expired            | Just-saved token: is_expired() == False           |
| 35  | test_absent_token_is_expired            | No file → is_expired() == True (safe default)     |
| 36  | test_token_age_hours_is_near_zero       | Age of just-saved token < 0.01h                   |
| 37  | test_token_age_returns_none_when_absent | No file → token_age_hours() == None               |
| 38  | test_clear_removes_file                 | clear() deletes file, load() returns None         |
| 39  | test_overwrite_updates_saved_at         | Second save() replaces first, timestamp advances  |
| 40  | test_corrupted_file_returns_none        | Malformed JSON → (None, None), no crash           |
| 41  | test_is_expired_with_tolerance          | tolerance=23.999h → fresh token still not expired |

---

## FILE: tests/test_modules.py  (71 tests ✅)

### TestATOProtection (8) — `modules/ato_protection.py`
| #   | Test                                    | Proves                                      |
| --- | --------------------------------------- | ------------------------------------------- |
| 42  | test_set_retrace_points                 | Sets buffer on both CE and PE sides         |
| 43  | test_ce_breach_triggers_protection      | spot ≥ ce_strike + retrace → buy CE ATO     |
| 44  | test_pe_breach_triggers_protection      | spot ≤ pe_strike − retrace → buy PE ATO     |
| 45  | test_ce_retracement_exits_ato           | spot retreats below ce_strike → sell CE ATO |
| 46  | test_pe_retracement_exits_ato           | spot retreats above pe_strike → sell PE ATO |
| 47  | test_no_breach_when_within_range        | spot inside range → no orders placed        |
| 48  | test_ce_ato_idempotency_skips_duplicate | ATO already triggered → no duplicate order  |
| 49  | test_pe_ato_idempotency_skips_duplicate | Same for PE side                            |

### TestATOStartupScan (15) — `modules/ato_protection.py._startup_scan()`
| #   | Test                                                    | Proves                                                     |
| --- | ------------------------------------------------------- | ---------------------------------------------------------- |
| 50  | test_pe_breach_adopts_manual_ato                        | Manual PE ATO in broker position → adopted cleanly         |
| 51  | test_ce_breach_adopts_manual_ato                        | Manual CE ATO in broker position → adopted cleanly         |
| 52  | test_pe_breach_auto_places_when_no_manual_ato           | No manual → auto-places PE ATO order                       |
| 53  | test_ce_breach_auto_places_when_no_manual_ato           | No manual → auto-places CE ATO order                       |
| 54  | test_no_breach_no_action                                | Spot inside range → no ATO change on startup               |
| 55  | test_stale_ce_state_is_reset                            | state has CE triggered but broker has no position → resets |
| 56  | test_stale_pe_state_is_reset                            | Same for PE side                                           |
| 57  | test_prior_day_ato_kept_when_broker_position_still_open | Position still open → ATO kept                             |
| 58  | test_qty_mismatch_adopts_but_fires_mismatch_event       | Qty ≠ expected → adopt + fire event                        |
| 59  | test_startup_scan_disabled_via_config                   | `startup_scan.enabled=false` → scan skipped                |
| 60  | test_scan_skips_when_no_positions                       | Empty positions → scan returns early                       |
| 61  | test_scan_skips_when_ltp_fails                          | LTP fetch returns None → scan aborts safely                |
| 62  | test_both_sides_breached_both_adopted                   | Both CE + PE found in broker → both adopted                |
| 63  | test_startup_scan_publishes_scan_done_event             | Event.STARTUP_SCAN_DONE published after scan               |
| 64  | test_adopted_ato_hands_off_to_retracement               | Adopted ATO immediately enters retrace-watch               |

### TestBatmanEntry (1) — `modules/batman_entry.py`
| #   | Test                    | Proves                          |
| --- | ----------------------- | ------------------------------- |
| 65  | test_deploy_iron_condor | Places 4 legs, records in state |

### TestProfitTrailing (1) — `modules/profit_trailing.py`
| #   | Test                     | Proves                                          |
| --- | ------------------------ | ----------------------------------------------- |
| 66  | test_hard_stop_detection | MTM below hard_stop_loss → emergency exit fires |

### TestEmergencyExit (2) — `modules/emergency_exit.py`
| #   | Test                                 | Proves                                 |
| --- | ------------------------------------ | -------------------------------------- |
| 67  | test_execute_exit                    | All open positions closed at market    |
| 68  | test_emergency_exit_resets_ato_state | ATO flags cleared after emergency exit |

### TestModuleLifecycle (2) — `core/module_base.py`
| #   | Test                           | Proves                                        |
| --- | ------------------------------ | --------------------------------------------- |
| 69  | test_module_disable_via_config | `enabled=false` → module does not tick        |
| 70  | test_status_dict               | status() returns enabled, running, last_error |

### TestConfigValidation (4) — `core/config.py`
| #   | Test                           | Proves                                              |
| --- | ------------------------------ | --------------------------------------------------- |
| 71  | test_valid_config_passes       | Correct config → no exception                       |
| 72  | test_missing_key_raises        | Missing required key → ConfigError                  |
| 73  | test_invalid_lot_size_raises   | lot_size=0 → ConfigError                            |
| 74  | test_positive_hard_stop_raises | hard_stop_loss > 0 → ConfigError (must be negative) |

### TestModuleAutoRestart (1) — `core/module_base.py`
| #   | Test                       | Proves                                      |
| --- | -------------------------- | ------------------------------------------- |
| 75  | test_auto_restart_on_crash | Module crash → auto-restarted, error logged |

### TestNextEntryDate (4) — `bot/algo_scheduler.py`
| #   | Test                                       | Proves                                 |
| --- | ------------------------------------------ | -------------------------------------- |
| 76  | test_returns_next_wednesday_from_monday    | Monday → next Wednesday                |
| 77  | test_returns_next_wednesday_from_wednesday | Wednesday → same day                   |
| 78  | test_returns_next_wednesday_from_saturday  | Saturday → 4 days forward to Wednesday |
| 79  | test_skips_holiday_wednesday               | Holiday Wed → Thursday                 |

### TestDeployHandlerHelpers (9) — `bot/handlers/deploy_handler.py`
| #   | Test                                              | Proves                                           |
| --- | ------------------------------------------------- | ------------------------------------------------ |
| 80  | test_parse_symbol_ce                              | NIFTY25APR23000CE → correct tuple                |
| 81  | test_parse_symbol_pe                              | NIFTY25APR22000PE → correct tuple                |
| 82  | test_parse_symbol_invalid_returns_none            | INVALID → None                                   |
| 83  | test_parse_symbol_banknifty                       | BANKNIFTY not matched (NIFTY prefix check)       |
| 84  | test_classify_legs_correct                        | 4 positions → (pe_buy, pe_sell, ce_sell, ce_buy) |
| 85  | test_classify_legs_empty_returns_none             | Empty list → None                                |
| 86  | test_classify_legs_duplicate_ce_sell_returns_none | 2 CE SELL → ambiguous → None                     |
| 87  | test_to_state_leg_sell_position                   | SHORT position → side=SELL in StateLeg           |
| 88  | test_to_state_leg_buy_position                    | LONG position → side=BUY in StateLeg             |

### TestAlgoSchedulerState (8) — `bot/algo_scheduler.py`
| #   | Test                                                      | Proves                                                    |
| --- | --------------------------------------------------------- | --------------------------------------------------------- |
| 89  | test_status_includes_deployment_fields                    | status() includes confirmed, batman_done, next_entry_date |
| 90  | test_tick_skips_when_batman_done                          | batman_done=True → tick is no-op                          |
| 91  | test_tick_skips_when_not_deployed                         | deployment.confirmed=False → tick is no-op                |
| 92  | test_handle_time_selection_stores_time                    | Time picked → stored in state                             |
| 93  | test_handle_time_selection_overrides_previous             | Second pick replaces first                                |
| 94  | test_stop_algo_sets_manually_stopped                      | /pause → state.manually_stopped=True                      |
| 95  | test_resume_algo_blocked_when_not_deployed                | /resume with no deployment → rejected                     |
| 96  | test_tick_sends_prompt_when_deployed_and_past_prompt_time | Past prompt time + deployed → sends prompt                |

### TestDeploymentStateDefaults (5) — `core/state.py`
| #   | Test                                          | Proves                                  |
| --- | --------------------------------------------- | --------------------------------------- |
| 97  | test_deployment_confirmed_defaults_false      | Fresh state: confirmed=False            |
| 98  | test_deployment_batman_done_defaults_false    | Fresh state: batman_done=False          |
| 99  | test_deployment_next_entry_date_defaults_none | Fresh state: next_entry_date=None       |
| 100 | test_deployment_confirmed_can_be_set          | set confirmed=True → persists           |
| 101 | test_new_cycle_resets_batman_done             | batman_done reset at start of new cycle |

### TestATOMaxCycles (4) — `modules/ato_protection.py`
| #   | Test                                  | Proves                                   |
| --- | ------------------------------------- | ---------------------------------------- |
| 102 | test_ce_max_cycles_blocks_after_limit | CE ATO cycle 3/3 → 4th breach ignored    |
| 103 | test_pe_max_cycles_blocks_after_limit | PE same                                  |
| 104 | test_max_cycles_zero_means_unlimited  | max_cycles=0 → never blocked             |
| 105 | test_max_cycles_event_published_once  | MAX_CYCLES_REACHED event fires once only |

### TestAlgoSchedulerEODPrompt (5) — `bot/algo_scheduler.py`
| #   | Test                                              | Proves                               |
| --- | ------------------------------------------------- | ------------------------------------ |
| 106 | test_eod_prompt_sent_on_expiry_day                | Tuesday + deployed → EOD prompt sent |
| 107 | test_eod_prompt_fires_on_any_day_when_deployed    | Not restricted to Tuesday            |
| 108 | test_eod_prompt_not_sent_twice_on_same_day        | Same-day idempotency                 |
| 109 | test_eod_prompt_not_sent_when_batman_already_done | batman_done=True → skip              |
| 110 | test_eod_prompt_not_sent_when_not_deployed        | Not deployed → skip                  |

---

## FILE: tests/test_resilience.py  (18 tests ✅)

### TestRetry (6) — `core/resilience.py`
| #   | Test                                     | Proves                                      |
| --- | ---------------------------------------- | ------------------------------------------- |
| 111 | test_succeeds_on_first_try               | No retry needed                             |
| 112 | test_retries_on_transient_error          | 2 failures then success                     |
| 113 | test_raises_after_max_attempts           | Exhausted → raises BrokerError              |
| 114 | test_does_not_retry_non_retryable_errors | ValueError → re-raised immediately          |
| 115 | test_custom_retryable_exceptions         | Caller can specify which exceptions retry   |
| 116 | test_on_retry_callback                   | on_retry callback called with attempt count |

### TestCircuitBreaker (9) — `core/resilience.py`
| #   | Test                                | Proves                                            |
| --- | ----------------------------------- | ------------------------------------------------- |
| 117 | test_starts_closed                  | Initial state is CLOSED (pass-through)            |
| 118 | test_opens_after_threshold_failures | N failures → state=OPEN                           |
| 119 | test_success_resets_count           | Success mid-way → failure count resets            |
| 120 | test_half_open_after_timeout        | After reset_timeout: OPEN→HALF_OPEN               |
| 121 | test_context_manager_success        | No exception → CB stays closed                    |
| 122 | test_context_manager_failure        | Exception inside → failure counted                |
| 123 | test_open_circuit_raises            | OPEN state → CircuitOpenError immediately         |
| 124 | test_protect_decorator              | @protect works as decorator on function           |
| 125 | test_status_dict                    | status() returns state, failures, last_failure_at |

### TestConfirmOrder (4) — `core/resilience.py`
| #   | Test                           | Proves                               |
| --- | ------------------------------ | ------------------------------------ |
| 126 | test_confirm_traded            | Order status=TRADED → returns True   |
| 127 | test_confirm_rejected_raises   | Status=REJECTED → OrderRejectedError |
| 128 | test_confirm_timeout           | Status never TRADED → TimeoutError   |
| 129 | test_confirm_eventually_traded | PENDING × N then TRADED → True       |

---

## PLANNED TESTS (not yet written)

### tests/test_kavach.py  (~35 planned) 🔲 BATCH 2

| Class                   | Tests | Status blocker                      |
| ----------------------- | ----- | ----------------------------------- |
| TestDeployWizardFlow    | 12    | kavach/bot.py not written           |
| TestDeployWizardCancel  | 4     | "                                   |
| TestDeployWizardTimeout | 2     | "                                   |
| TestDeployFilePersist   | 5     | kavach/deploy_wizard.py not written |
| TestKavachCommands      | 8     | "                                   |
| TestBatmanComplete      | 4     | "                                   |

### tests/test_drishti.py  (~24 planned) 🔲 BATCH 3

| Class                     | Tests | Status blocker             |
| ------------------------- | ----- | -------------------------- |
| TestTokenReceipt          | 6     | drishti/bot.py not written |
| TestTokenValidation       | 4     | "                          |
| TestTokenReminderSchedule | 6     | "                          |
| TestSilentNotifications   | 4     | "                          |
| TestHealthAlert           | 4     | "                          |

### tests/test_lakshmi.py  (~16 planned) 🔲 BATCH 4

| Class           | Tests | Status blocker             |
| --------------- | ----- | -------------------------- |
| TestMTMAlerts   | 6     | lakshmi/bot.py not written |
| TestProfitAlert | 3     | "                          |
| TestPnlCommand  | 4     | "                          |
| TestEODSummary  | 3     | "                          |

### tests/test_integration.py  (~15 planned) 🔲 BATCH 5

| Class                      | Tests | Status blocker                                     |
| -------------------------- | ----- | -------------------------------------------------- |
| TestATOReadsDeploymentFile | 5     | ato_protection._load_deployment_file() not written |
| TestDeployWizardArmsATO    | 3     | KAVACH + ATO both needed                           |
| TestBatmanCompleteFullFlow | 4     | All bots needed                                    |
| TestVPSRestartFlow         | 3     | main.py asyncio rewrite needed                     |
