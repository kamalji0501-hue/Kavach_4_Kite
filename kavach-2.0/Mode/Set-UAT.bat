@echo off
title Batman Mode - UAT
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    pause
    exit /b 1
)
echo Setting Batman mode to UAT (virtual broker)...
".venv\Scripts\python.exe" scripts\set_batman_mode.py uat
echo.
echo Paste Sensibull screenshot in: uat\deployed_positions\
echo Then run: Mode\Prepare-UAT.bat
pause
