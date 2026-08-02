@echo off

REM Shared pre-start guard — called from start Drishti/Kavach/Jagran.bat

REM %1 = robot key (drishti|kavach|jagran), %2 = optional "force"

setlocal

set ROBOT=%~1

set FORCE=%~2

if "%ROBOT%"=="" (

    echo ERROR: _preflight_start.bat requires robot name.

    exit /b 1

)

if /I "%FORCE%"=="force" (

    ".venv\Scripts\python.exe" scripts\ensure_bot_stopped.py %ROBOT% --force

) else (

    ".venv\Scripts\python.exe" scripts\ensure_bot_stopped.py %ROBOT%

)

exit /b %ERRORLEVEL%

