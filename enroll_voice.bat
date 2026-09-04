@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found. Run run.bat once first, it creates it.
    echo.
    pause
    exit /b 1
)

call "venv\Scripts\activate.bat"

echo.
echo This records about 30 seconds of your voice and stores a fingerprint of it,
echo so that in every transcript you are Person 1 and the other voice is Person 2.
echo The recording stays on this PC, in the voice\ folder.
echo.

python enroll_voice.py %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo Enrollment failed. See the messages above.
pause
exit /b %RC%
