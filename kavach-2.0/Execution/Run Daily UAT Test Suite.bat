@echo off
setlocal
cd /d "%~dp0\.."
call "Mode\Set-UAT.bat" >nul 2>&1
echo === Daily UAT Test Suite ===
".venv\Scripts\python.exe" scripts\run_uat_daily_test_suite.py %*
set RC=%ERRORLEVEL%
echo.
if %RC% equ 0 (
  echo PASS — see daily_test_execution\LATEST_RUN.md and test_matrix.xlsx
) else (
  echo FAIL exit %RC% — fix failures and re-run
)
exit /b %RC%
