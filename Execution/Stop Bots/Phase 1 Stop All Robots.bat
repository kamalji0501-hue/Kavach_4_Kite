@echo off

title Phase 1 — Stop All Robots

setlocal

set SILENT=%~1



cd /d "%~dp0..\.."

if %ERRORLEVEL% NEQ 0 (

    echo ERROR: Could not open project folder.

    if /I not "%SILENT%"=="silent" pause

    exit /b 1

)



if /I not "%SILENT%"=="silent" (

    echo ========================================

    echo   Phase 1 — Stop All Robots

    echo   DRISHTI, KAVACH, JAGRAN

    echo ========================================

    echo.

    echo Up to 5 stop attempts. Logs: logs\runtime\...\launchers\stop_all\

    echo Do NOT close bot windows with X — use stop .bat files.

    echo.

)



if not exist ".venv\Scripts\python.exe" (

    echo ERROR: .venv\Scripts\python.exe not found.

    if /I not "%SILENT%"=="silent" pause

    exit /b 1

)



if /I "%SILENT%"=="silent" (

    ".venv\Scripts\python.exe" scripts\phase1_stop_all.py --silent

) else (

    ".venv\Scripts\python.exe" scripts\phase1_stop_all.py

)

set RC=%ERRORLEVEL%



if not "%RC%"=="0" (

    if /I not "%SILENT%"=="silent" (

        echo.

        echo Stop All failed. See popup and log under launchers\stop_all\

        pause

    )

    endlocal & exit /b %RC%

)



if /I not "%SILENT%"=="silent" (

    echo.

    echo SUCCESS: All Phase 1 robots stopped.

    echo Closing this window in 5 seconds...

    "%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul 2>&1

)



endlocal

exit /b 0

