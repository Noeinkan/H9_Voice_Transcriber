@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating Python 3.12 virtual environment...
    py -3.12 -m venv venv
    if errorlevel 1 exit /b 1
)

call "venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -c "import torch, buzz" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies (first run may take 10+ minutes)...
    python -m pip install -U pip
    pip install -U torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
    pip install nvidia-cublas-cu12==12.9.1.4 nvidia-cuda-cupti-cu12==12.9.79 nvidia-cuda-runtime-cu12==12.9.79 --extra-index-url https://pypi.ngc.nvidia.com
    pip install buzz-captions
    pip install --force-reinstall torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
    if errorlevel 1 exit /b 1
)

python -c "from transcribe import model_is_ready; import sys; sys.exit(0 if model_is_ready() else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Model weights not found. Run download_model.bat first ^(one-time, ~3 GB^).
    echo.
    pause
    exit /b 1
)

python transcribe.py
set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% EQU 0 (
    echo Finished. Check the output\ folder for .txt files.
) else (
    echo Transcription failed. See transcripts.log for details.
)
pause
exit /b %EXIT_CODE%
