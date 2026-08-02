@echo off

cd /d "%~dp0.."

echo === Quick UAT positions (no bot restart) ===

.venv\Scripts\python.exe scripts\quick_uat_positions_gate.py

exit /b %ERRORLEVEL%

