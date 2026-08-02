@echo off
echo Starting Batman v3 (DRISHTI + KAVACH + LAKSHMI bots)...
echo.

REM Activate virtual environment and run main.py
call .venv\Scripts\activate.bat
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Failed to start Batman v3
    echo Please check:
    echo 1. Virtual environment exists at .venv
    echo 2. Python dependencies are installed
    echo 3. Bot token files are configured
    pause
    exit /b %ERRORLEVEL%
)
