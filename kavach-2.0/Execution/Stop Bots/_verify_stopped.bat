@echo off

REM Post-stop verification — %1 = robot key (drishti|kavach|jagran)

setlocal

set ROBOT=%~1

if "%ROBOT%"=="" exit /b 1

".venv\Scripts\python.exe" scripts\ensure_bot_stopped.py %ROBOT% --after-stop

exit /b %ERRORLEVEL%

