@echo off
rem Double-click or run from cmd. Arguments are passed to start.ps1 (e.g. start.bat -Camera demo).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
