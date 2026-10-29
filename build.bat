@echo off
REM Builds MediaDownloaderPro.exe  (requires Python 3.10+ on PATH)
REM Optional: put ffmpeg.exe in this folder first to bundle it (needed for MP3/M4A and HD merging).
python -m pip install -r requirements.txt -r requirements-build.txt || goto :err
set EXTRA=
if exist ffmpeg.exe set EXTRA=--add-binary "ffmpeg.exe;."
python -m PyInstaller --noconfirm --onefile --windowed --name MediaDownloaderPro ^
  --add-data "static;static" --collect-all yt_dlp --collect-all webview %EXTRA% server.py || goto :err
echo.
echo Done: dist\MediaDownloaderPro.exe
pause & exit /b
:err
echo Build failed. & pause
