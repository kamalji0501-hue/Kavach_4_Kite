@echo off
REM Phase 1 status — canonical copy (mirrored in Stop Bots folder)
title Batman — Bot process status
cd /d "%~dp0..\.."
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Could not open project folder.
    pause
    exit /b 1
)
echo.
".venv\Scripts\python.exe" scripts\bot_status.py all
echo.
pause
