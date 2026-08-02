@echo off
cd /d "%~dp0.."
echo === UAT chat positions validate ===
if not exist "uat\deployed_positions\positions.json" (
  echo MISSING: uat\deployed_positions\positions.json
  echo Paste Sensibull screenshot in Cursor with: UAT POSITIONS @uat-sensibull-from-chat
  exit /b 1
)
.venv\Scripts\python.exe backtest_engine\tools\validate_fixture.py --fixture uat\deployed_positions\positions.json
exit /b %ERRORLEVEL%
