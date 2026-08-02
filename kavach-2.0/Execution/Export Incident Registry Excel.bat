@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\incident_mgmt.py export-excel
echo.
echo Open: docs\incidents\incident_registry.xlsx
pause
