# Media Downloader Pro
Local web app. Backend: FastAPI + yt-dlp. Storage: SQLite (`downloads.db`). Bound to 127.0.0.1 only.

    pip install -r requirements.txt     # also install ffmpeg (needed for MP3/M4A and merging 720p+ streams)
    python server.py                    # open http://127.0.0.1:8765

Pause = stop and keep the partial file; Resume continues from it. Private, login-gated, age-restricted and DRM videos
are reported as blocked and never bypassed. A download is only marked "completed" after the file is verified on disk.
Keep yt-dlp current (`pip install -U yt-dlp`) since platforms change often.

## Build the Windows .exe
1. Install Python 3.10+ (tick "Add to PATH").
2. Download `ffmpeg.exe` (ffmpeg-release-essentials build) and put it in this folder to bundle it.
3. Double-click `build.bat` -> `dist\MediaDownloaderPro.exe` (single file, opens in its own window).
History and settings are stored in `%APPDATA%\MediaDownloaderPro`.
