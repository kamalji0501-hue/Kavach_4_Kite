@echo off
title Batman Supervisor — Stop All
cd /d "%~dp0..\.."
echo.
echo Stopping all Phase 1 bots via supervisor...
echo.
".venv\Scripts\python.exe" scripts\bot_supervisor.py stop
echo.
pause
