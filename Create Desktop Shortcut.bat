@echo off
REM Double-click once to put "H9 Voice Transcriber" on the desktop.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_shortcut.ps1"
echo.
pause
