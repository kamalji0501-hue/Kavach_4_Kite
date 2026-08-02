@echo off

title Phase 1 — Start All Robots (launcher)

setlocal

set FORCE=%~1



cd /d "%~dp0..\.."

if %ERRORLEVEL% NEQ 0 (

    echo ERROR: Could not open project folder.

    pause

    exit /b 1

)



echo ========================================

echo   Phase 1 — Start All Robots

echo   DRISHTI, then KAVACH, then JAGRAN

echo ========================================

echo.

echo Waits up to 2 minutes for all bots to show RUNNING.

echo Logs: logs\runtime\...\launchers\start_all\

echo Guide: Execution\PHASE1_ROBOT_LAUNCHER.md

echo.



if not exist ".venv\Scripts\python.exe" (

    echo ERROR: .venv\Scripts\python.exe not found.

    pause

    exit /b 1

)



if /I "%FORCE%"=="force" (

    ".venv\Scripts\python.exe" scripts\phase1_start_all.py --force

) else (

    ".venv\Scripts\python.exe" scripts\phase1_start_all.py

)

set RC=%ERRORLEVEL%



if not "%RC%"=="0" (

    echo.

    echo Start All failed or timed out. See popup and launchers\start_all\ logs.

    pause

    endlocal & exit /b %RC%

)



echo.

echo SUCCESS: All Phase 1 robots verified RUNNING.

echo Three bot windows should be open. Status: Show Bot Status.bat

echo Closing this launcher window in 5 seconds...

"%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul 2>&1



endlocal

exit /b 0

