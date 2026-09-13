@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\WebReport.ps1" -Action stop %*
set "WEBREPORT_EXIT_CODE=%ERRORLEVEL%"
if not "%WEBREPORT_EXIT_CODE%"=="0" pause
exit /b %WEBREPORT_EXIT_CODE%
