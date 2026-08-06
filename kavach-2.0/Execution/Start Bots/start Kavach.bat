@echo off

title KAVACH Bot - Running

setlocal

set FORCE=%~1



echo ========================================

echo   Starting KAVACH Telegram Bot

echo ========================================

echo.

echo OPERATOR RULE: Start/stop ONLY via Start Bots and Stop Bots .bat files.

echo Do NOT close this window with the X button — use stop Kavach.bat.

echo.



cd /d "%~dp0..\.."

if %ERRORLEVEL% NEQ 0 (

    echo ERROR: Could not open project folder.

    pause

    exit /b 1

)



if not exist ".venv\Scripts\python.exe" (

    echo ERROR: Virtual environment not found.

    pause

    exit /b 1

)



if not exist "run_kavach2.py" (

    echo ERROR: run_kavach2.py not found in project root.

    pause

    exit /b 1

)



echo Project folder: %CD%

echo.

echo Step 1: Stopping any old KAVACH instances (stop script)...

call "%~dp0..\Stop Bots\stop Kavach.bat" silent

"%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul 2>&1

if errorlevel 1 ping 127.0.0.1 -n 3 >nul



echo Step 2: Verifying KAVACH is fully stopped...

call "%~dp0_preflight_start.bat" kavach %FORCE%

if not "%ERRORLEVEL%"=="0" (

    echo.

    echo START ABORTED. Fix the issue above, then run this start bat again.

    pause

    exit /b 1

)



echo.

echo Step 3: Starting KAVACH...

echo Status anytime: Execution\Show Bot Status.bat

echo Requires valid Dhan JWT from DRISHTI for /positions and /register.

echo.



set BATMAN_LAUNCHED_VIA_BAT=1

".venv\Scripts\python.exe" run_kavach2.py



echo.

echo KAVACH has stopped. To stop from another window use stop Kavach.bat.

pause

endlocal

