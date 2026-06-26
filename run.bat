@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "LOG_FILE=%~dp0run.log"
set "STEP=0"

call :log "==== run.bat started ===="

REM ============================================================
REM STEP 0: ffmpeg on PATH
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: checking ffmpeg / ffprobe on PATH"
where ffmpeg >nul 2>&1
if errorlevel 1 goto :missing_ffmpeg
where ffprobe >nul 2>&1
if errorlevel 1 goto :missing_ffmpeg
call :log "  ffmpeg and ffprobe found"
goto :ffmpeg_ok

:missing_ffmpeg
call :log "  ffmpeg NOT found on PATH"
echo.
echo ffmpeg is not installed or not on PATH.
echo Whisper transcription needs ffmpeg to read .m4a files.
echo.
echo Install it with:  winget install Gyan.FFmpeg
echo Then close this window, open a fresh terminal, and re-run run.bat.
echo.
pause
exit /b 1
:ffmpeg_ok

REM ============================================================
REM STEP 1: virtual environment
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: checking virtual environment at venv\Scripts\python.exe"
if exist "venv\Scripts\python.exe" goto :venv_ok
call :log "  venv missing - creating with py -3.12"
py -3.12 -m venv venv
if errorlevel 1 goto :fail_venv
call :log "  venv created"
:venv_ok
call :log "  venv present"

REM ============================================================
REM STEP 2: activate
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: activating venv"
call "venv\Scripts\activate.bat"
if errorlevel 1 goto :fail_activate
call :log "  venv activated"

REM ============================================================
REM STEP 3: dependencies
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: checking dependencies (torch, buzz)"
python -c "import torch, buzz" >nul 2>&1
if errorlevel 1 goto :install_deps
call :log "  dependencies already present, skipping install"
goto :deps_ok

:install_deps
call :log "  dependencies missing - installing (first run can take 10+ minutes)"
echo Installing dependencies ^^(first run may take 10+ minutes^)^. Live output below; mirrored to run.log.
echo.

call :run_step "pip install -U pip"  python -m pip install -U pip
if !RC! NEQ 0 goto :fail_deps

call :run_step "pip install torch + torchaudio (CUDA 12.9 wheels)"  pip install -U torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
if !RC! NEQ 0 goto :fail_deps

call :run_step "pip install nvidia-cublas / cuda-cupti / cuda-runtime"  pip install nvidia-cublas-cu12==12.9.1.4 nvidia-cuda-cupti-cu12==12.9.79 nvidia-cuda-runtime-cu12==12.9.79 --extra-index-url https://pypi.ngc.nvidia.com
if !RC! NEQ 0 goto :fail_deps

call :run_step "pip install buzz-captions"  pip install buzz-captions
if !RC! NEQ 0 goto :fail_deps

call :run_step "pip install --force-reinstall torch/torchaudio CUDA wheels"  pip install --force-reinstall torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
if !RC! NEQ 0 goto :fail_deps

call :log "  dependencies installed"
:deps_ok

REM ============================================================
REM STEP 4: model weights
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: checking model weights in models\large-v3\"
python check_model.py >nul 2>&1
set "RC=!ERRORLEVEL!"
if !RC! NEQ 0 goto :missing_model
call :log "  check_model.py returned 0 - model present"
goto :model_ok

:missing_model
call :log "  check_model.py returned !RC! - model missing or incomplete"
echo.
echo Model weights not found. Run download_model.bat first ^(one-time, ~3 GB^).
echo.
pause
exit /b 1
:model_ok

REM ============================================================
REM STEP 5: transcribe
REM ============================================================
set /a STEP+=1
call :log "STEP !STEP!: starting transcription (python transcribe.py)"
echo.
echo Starting transcription. Live output below; transcripts.log is updated as files complete.
echo   ^(Tail it in another terminal: type transcripts.log  or  Get-Content transcripts.log -Wait^)
echo.

set "TEMP_OUT=%TEMP%\h9_transcribe_%RANDOM%.txt"
python transcribe.py > "!TEMP_OUT!" 2>&1
set "RC=!ERRORLEVEL!"
type "!TEMP_OUT!"
del "!TEMP_OUT!" >nul 2>&1
call :log "  python transcribe.py exited with !RC!"

echo.
if !RC! EQU 0 goto :finished_ok
call :log "STEP !STEP!: FAILED with errorlevel !RC!"
echo Transcription failed. See transcripts.log and run.log for details.
pause
exit /b !RC!

:finished_ok
call :log "STEP !STEP!: finished successfully"
echo Finished. Check the output\ folder for .txt files.
pause
exit /b 0

REM ============================================================
REM failure paths
REM ============================================================
:fail_venv
call :log "  FAILED to create venv"
echo.
echo Failed to create virtual environment.
echo Make sure Python 3.12 is installed and on PATH.
echo Try: py -3.12 --version
echo.
pause
exit /b 1

:fail_activate
call :log "  FAILED to activate venv"
pause
exit /b 1

:fail_deps
call :log "  FAILED during pip install (rc=!RC!)"
echo.
echo Dependency installation failed. See run.log for details.
echo.
pause
exit /b 1

REM ============================================================
REM :log <message>  - append a timestamped line to LOG_FILE and console
REM ============================================================
:log
set "TS=!DATE! !TIME!"
>> "!LOG_FILE!" echo [!TS!] %~1
echo [!TS!] %~1
exit /b

REM ============================================================
REM :run_step <label> <command...>
REM   Run command, capture its exit code into !RC!.
REM   Stream stdout+stderr to console live, mirror to LOG_FILE
REM   (blank lines stripped). Real-time because we use a small
REM   Python tee (run_with_log.py) so both halves happen in one
REM   subprocess pipe and we can still read the upstream's exit code.
REM ============================================================
:run_step
set "STEP_LABEL=%~1"
shift
call :log "    > %STEP_LABEL%"
python "%~dp0run_with_log.py" "!LOG_FILE!" -- %*
set "RC=!ERRORLEVEL!"
call :log "    %STEP_LABEL% returned !RC!"
exit /b
