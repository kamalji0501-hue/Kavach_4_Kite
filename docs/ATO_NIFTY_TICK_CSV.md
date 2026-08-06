# ATO + NIFTY tick CSV

## Purpose

After Kavach `/register`, tick-by-tick rows are appended for real-money debug:

- NIFTY LTP (every websocket/REST tick)
- Registered ATO CE option LTP (from DRISHTI option poll)
- Registered ATO PE option LTP
- AUTO vs CUSTOM mode for each side

## Columns

date_time_ist, nifty_ltp, ce_ato_symbol, ce_ato_strike, ce_ato_mode, ce_ato_ltp,
pe_ato_symbol, pe_ato_strike, pe_ato_mode, pe_ato_ltp, source

`source`: nifty_ws | nifty_rest | nifty_cache | option_poll | register

## Paths

Primary (runtime data disk):

`Trading_Runtime_Rahul/Data/.../ato_tick_csv/YYYY-MM/ato_nifty_ce_pe_YYYYMMDD.csv`

Mirror under DRISHTI day logs: `.../drishti/logs/ato_tick_csv/`

## Kavach

Confirm and Arm Batman announces the CSV path in Telegram.

## Module

`core/ato_nifty_tick_csv.py` — buffered append (flush ~1s / 25 rows).
