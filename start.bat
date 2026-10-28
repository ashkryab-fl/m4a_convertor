@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "converter_exit=%errorlevel%"
if not "%converter_exit%"=="0" pause
exit /b %converter_exit%
