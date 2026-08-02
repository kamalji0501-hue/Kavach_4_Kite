@echo off

setlocal

set SILENT=%~1



cd /d "%~dp0..\.."

if %ERRORLEVEL% NEQ 0 (

    if /I not "%SILENT%"=="silent" (

        echo ERROR: Could not open project folder.

        pause

    )

    exit /b 1

)



if /I not "%SILENT%"=="silent" (

    title Stop SARANSH Bot

    echo ========================================

    echo   Stopping SARANSH Telegram Bot

    echo ========================================

    echo.

    echo OPERATOR RULE: Always stop here — do NOT close the running bot window with X.

    echo Retries up to 10 seconds. On success this window closes in 5 seconds.

    echo.

)



if not exist ".venv\Scripts\python.exe" (

    if /I not "%SILENT%"=="silent" (

        echo ERROR: .venv\Scripts\python.exe not found.

        pause

    )

    exit /b 1

)



if /I "%SILENT%"=="silent" (

    ".venv\Scripts\python.exe" scripts\stop_saransh.py --silent

) else (

    ".venv\Scripts\python.exe" scripts\stop_saransh.py

)

set STOP_RC=%ERRORLEVEL%



if not "%STOP_RC%"=="0" (

    if /I not "%SILENT%"=="silent" (

        echo.

        echo ERROR: Stop script failed with code %STOP_RC%.

        pause

    )

    endlocal & exit /b %STOP_RC%

)



call "%~dp0_verify_stopped.bat" saransh

set VERIFY_RC=%ERRORLEVEL%

if not "%VERIFY_RC%"=="0" (

    if /I not "%SILENT%"=="silent" (

        echo.

        echo ERROR: SARANSH processes still detected after stop. Run this stop bat again.

        pause

    )

    endlocal & exit /b %VERIFY_RC%

)



if /I not "%SILENT%"=="silent" (

    echo.

    echo SUCCESS: SARANSH fully stopped. Confirm anytime: Execution\Show Bot Status.bat

    echo Closing in 5 seconds...

    timeout /t 5 /nobreak >nul

)



endlocal

exit /b 0
