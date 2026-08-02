@echo off

REM Phase 1 status — mirror of Start Bots\Show Bot Status.bat

call "%~dp0..\Start Bots\Show Bot Status.bat" %*

exit /b %ERRORLEVEL%

