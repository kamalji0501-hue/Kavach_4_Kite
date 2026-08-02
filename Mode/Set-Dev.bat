@echo off
title Batman Mode - DEV
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    pause
    exit /b 1
)
echo Setting Batman mode to DEV...
".venv\Scripts\python.exe" scripts\set_batman_mode.py dev
echo.
echo Next: start bots via Execution\Start Bots\ (DRISHTI, KAVACH, JAGRAN)
pause
