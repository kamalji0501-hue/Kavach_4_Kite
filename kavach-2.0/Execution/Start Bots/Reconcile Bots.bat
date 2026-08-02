@echo off
title Batman — Reconcile Bots
cd /d "%~dp0..\.."
echo.
echo Healing stale locks before start/stop...
echo.
".venv\Scripts\python.exe" scripts\reconcile_bots.py all
echo.
pause
