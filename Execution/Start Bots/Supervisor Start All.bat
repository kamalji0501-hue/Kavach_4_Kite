@echo off
title Batman Supervisor — Start All
cd /d "%~dp0..\.."
echo.
echo Starting all Phase 1 bots via supervisor (recommended)...
echo.
".venv\Scripts\python.exe" scripts\bot_supervisor.py start --force --success-popup
echo.
pause
