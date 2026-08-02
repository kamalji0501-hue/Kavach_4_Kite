@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\run_agent_feedback_loop.py --restart drishti %*
pause
