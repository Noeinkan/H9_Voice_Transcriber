@echo off
REM Opens the H9 Voice Transcriber window. Builds the Python environment the
REM first time it is run. This is the file the desktop shortcut points at when
REM no frozen .exe has been built.
setlocal
cd /d "%~dp0"

if exist "dist\H9 Transcriber.exe" (
    start "" "dist\H9 Transcriber.exe"
    exit /b 0
)

if exist "venv\Scripts\pythonw.exe" goto :launch

echo.
echo First run: creating the Python environment and installing dependencies.
echo This takes 10 minutes or more. The window closes on its own when done.
echo.
py -3.12 -m venv venv
if errorlevel 1 goto :fail
call "venv\Scripts\activate.bat"
python -m pip install -U pip
python "%~dp0install_deps.py"
if errorlevel 1 goto :fail

:launch
start "" "venv\Scripts\pythonw.exe" "%~dp0desktop_app.py"
exit /b 0

:fail
echo.
echo Setup failed. Run run.bat from a terminal to see the full output,
echo or read run.log next to this file.
echo.
pause
exit /b 1
