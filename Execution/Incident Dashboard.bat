@echo off

title Batman — Incident dashboard

cd /d "%~dp0.."

if %ERRORLEVEL% NEQ 0 (

    echo ERROR: Could not open project folder.

    pause

    exit /b 1

)

echo.

".venv\Scripts\python.exe" scripts\incident_dashboard.py --days 7

echo.

pause

