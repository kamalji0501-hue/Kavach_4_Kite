@echo off
setlocal
set DIR=%~dp0
pushd "%DIR%\..\.."

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=.venv\bin\python

echo Stopping any old RATRIPAL instances...
call "%DIR%\..\Stop Bots\stop Ratripal.bat" silent
timeout /t 2 /nobreak >nul

echo Verifying RATRIPAL is stopped...
call "%DIR%\_preflight_start.bat" ratripal %1
if errorlevel 1 (
    echo START ABORTED.
    popd
    exit /b 1
)

echo Starting RATRIPAL...
set BATMAN_LAUNCHED_VIA_BAT=1
"%PY%" run_ratripal.py

popd
endlocal
