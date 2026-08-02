@echo off
title Batman Mode - PROD
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    pause
    exit /b 1
)
echo Setting Batman mode to PROD...
".venv\Scripts\python.exe" scripts\set_batman_mode.py prod
echo.
echo PROD is for VPS with static IP. Do not start live orders on laptop without review.
pause
