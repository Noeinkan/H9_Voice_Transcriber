@echo off
setlocal
set "FFMPEG_BIN=C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
set "PATH=%FFMPEG_BIN%;%PATH%"
where ffmpeg >nul 2>&1 || (
    echo ffmpeg not found at: %FFMPEG_BIN%
    pause
    exit /b 1
)
where ffprobe >nul 2>&1 || (
    echo ffprobe not found at: %FFMPEG_BIN%
    pause
    exit /b 1
)
call "%~dp0run.bat"