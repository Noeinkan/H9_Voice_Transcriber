@echo off
setlocal
cd /d "%~dp0"
call "venv\Scripts\activate.bat"
echo Downloading large-v3 model (~3 GB). This is a one-time step.
python -c "from transcribe import download_model; download_model(); print('Model download complete.')"
pause
