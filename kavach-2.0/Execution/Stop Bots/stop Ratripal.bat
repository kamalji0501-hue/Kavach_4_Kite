@echo off
setlocal
set DIR=%~dp0
pushd "%DIR%\..\.."

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=.venv\bin\python

if /I "%1"=="silent" (
    "%PY%" scripts\stop_ratripal.py --silent
) else (
    "%PY%" scripts\stop_ratripal.py
)

call "%DIR%\_verify_stopped.bat" ratripal

popd
endlocal
