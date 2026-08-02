@echo off
setlocal
cd /d "%~dp0\.."
call "Mode\Set-UAT.bat" >nul 2>&1
echo === UAT E2E verification (headless) ===
".venv\Scripts\python.exe" scripts\run_uat_e2e_verification.py %*
set RC=%ERRORLEVEL%
if %RC% neq 0 (
  echo.
  echo FAILED exit %RC% — open UAT_E2E_AGENT.md for agent loop instructions.
)
exit /b %RC%
