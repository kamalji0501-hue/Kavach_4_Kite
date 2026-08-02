@echo off
setlocal
set DIR=%~dp0
pushd "%DIR%\..\.."

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=.venv\bin\python

echo Stopping any old KAVACH 2.0 instances...
call "%DIR%\..\Stop Bots\stop Kavach2.bat" silent
timeout /t 2 /nobreak >nul

echo Verifying KAVACH 2.0 is stopped...
call "%DIR%\_preflight_start.bat" kavach2 %1
if errorlevel 1 (
    echo START ABORTED.
    popd
    exit /b 1
)

echo Starting KAVACH 2.0...
set BATMAN_LAUNCHED_VIA_BAT=1
"%PY%" run_kavach2.py

popd
endlocal
