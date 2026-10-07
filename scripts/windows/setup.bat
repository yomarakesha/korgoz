@echo off
rem Double-click or run from cmd. Arguments are passed to setup.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
