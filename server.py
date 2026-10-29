"""Media Downloader Pro - local backend (FastAPI + yt-dlp). Run: python server.py"""
import json, os, re, shutil, sqlite3, subprocess, sys, threading, time, uuid
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

FROZEN = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))          # bundled read-only files
DATA = (Path(os.environ.get("APPDATA", Path.home())) / "MediaDownloaderPro") if FROZEN else BASE
DATA.mkdir(parents=True, exist_ok=True)
DB = sqlite3.connect(DATA / "downloads.db", check_same_thread=False)
LOCK = threading.RLock()
DB.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
DEFAULTS = {"folder": str(Path.home() / "Downloads" / "MediaDownloaderPro"),
            "quality": "1080", "format": "mp4", "concurrent": 3}

PLATFORMS = {"YouTube": ["youtube.com", "youtu.be"], "Facebook": ["facebook.com", "fb.watch"],
    "Instagram": ["instagram.com"], "TikTok": ["tiktok.com"], "X (Twitter)": ["x.com", "twitter.com"],
    "Reddit": ["reddit.com", "redd.it"], "Vimeo": ["vimeo.com"], "Dailymotion": ["dailymotion.com", "dai.ly"]}
def find_ffmpeg():
    for d in (BASE, Path(sys.executable).parent):
        if (d / "ffmpeg.exe").exists() or (d / "ffmpeg").exists(): return str(d)
    return str(Path(shutil.which("ffmpeg")).parent) if shutil.which("ffmpeg") else None
FFMPEG_DIR = find_ffmpeg(); HAS_FFMPEG = FFMPEG_DIR is not None

def detect(url):
    host = (urlparse(url).hostname or "").lower()
    for name, doms in PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in doms): return name
    return None

def settings():
    s = dict(DEFAULTS)
    for k, v in DB.execute("SELECT k,v FROM kv"): s[k] = json.loads(v)
    return s

def save(job):
    with LOCK:
        DB.execute("REPLACE INTO jobs VALUES(?,?)", (job["id"], json.dumps(job))); DB.commit()

JOBS, CTL = {}, {}
for _id, d in DB.execute("SELECT * FROM jobs"):
    j = json.loads(d)
    if j["status"] in ("downloading", "queued"): j.update(status="paused", speed=0, error="Interrupted - press Resume")
    JOBS[_id] = j

def friendly(e):
    m = str(e).lower()
    if "drm" in m: return "blocked", "This video is DRM-protected and cannot be downloaded."
    if any(x in m for x in ("private", "login", "sign in", "members-only", "authentication", "age-restricted", "confirm your age")):
        return "blocked", "This video is private, age/login-restricted or members-only. Access is not bypassed."
    if any(x in m for x in ("unavailable", "removed", "not available", "404", "does not exist")):
        return "blocked", "This video is unavailable or has been removed."
    if "unsupported url" in m: return "unsupported", "No downloadable video was found at this URL."
    return "error", re.sub(r"\x1b\[[0-9;]*m", "", str(e))[:300]

def fmt_selector(o):
    if o["audio"]: return "bestaudio[ext=m4a]/bestaudio/best"
    h = "" if o["quality"] == "best" else f"[height<={o['quality']}]"
    if o["format"] == "webm": return f"bv*{h}[ext=webm]+ba[ext=webm]/bv*{h}+ba/b{h}"
    return f"bv*{h}[ext=mp4]+ba[ext=m4a]/bv*{h}+ba/b{h}"

def run(job):
    ctl = CTL[job["id"]] = {"stop": None}
    o = job["opts"]; folder = Path(settings()["folder"]); folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]', "_", o["filename"]).strip() if o.get("filename") else "%(title).120B [%(id)s]"
    def hook(d):
        if ctl["stop"]: raise DownloadCancelled()
        if d["status"] == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            job.update(downloaded=d.get("downloaded_bytes") or 0, total=tot, speed=d.get("speed") or 0,
                       eta=d.get("eta"), progress=round(100 * (d.get("downloaded_bytes") or 0) / tot, 1) if tot else 0)
    opts = {"format": fmt_selector(o), "outtmpl": str(folder / (name + ".%(ext)s")), "progress_hooks": [hook],
            "continuedl": True, "noplaylist": True, "quiet": True, "no_warnings": True, "retries": 5,
            "merge_output_format": o["format"] if not o["audio"] else None,
            "ffmpeg_location": FFMPEG_DIR}
    if o["audio"]:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": o["audio"]}]
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(job["url"], download=True)
        rd = (info.get("requested_downloads") or [{}])[0]
        path = Path(rd.get("filepath") or y.prepare_filename(info))
        if o["audio"]: path = path.with_suffix("." + o["audio"])
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Download finished but no file was written to disk.")
        job.update(status="completed", progress=100, speed=0, eta=0, path=str(path), size=path.stat().st_size,
                   filename=path.name, finished=time.time(), error=None)
    except DownloadCancelled:
        if ctl["stop"] == "pause": job.update(status="paused", speed=0)
        else: job.update(status="cancelled", speed=0)
    except Exception as e:
        job.update(status="failed", speed=0, error=friendly(e)[1])
    save(job)

def scheduler():
    while True:
        time.sleep(0.7)
        with LOCK:
            active = sum(j["status"] == "downloading" for j in JOBS.values())
            for j in sorted(JOBS.values(), key=lambda x: x["created"]):
                if active >= int(settings()["concurrent"]): break
                if j["status"] == "queued":
                    j["status"] = "downloading"; active += 1
                    threading.Thread(target=run, args=(j,), daemon=True).start()
threading.Thread(target=scheduler, daemon=True).start()

app = FastAPI(title="Media Downloader Pro")

@app.middleware("http")
async def localhost_only(request: Request, call_next):
    if (request.headers.get("host", "").split(":")[0]) not in ("127.0.0.1", "localhost"):
        return JSONResponse({"detail": "Local access only"}, 403)
    return await call_next(request)

class Url(BaseModel): url: str
class Dl(BaseModel):
    url: str; quality: str = "1080"; format: str = "mp4"; audio: str | None = None
    filename: str | None = None; thumb: str | None = None; title: str | None = None; force: bool = False

@app.post("/api/probe")
def probe(b: Url):
    url = b.url.strip()
    if not re.match(r"https?://", url): raise HTTPException(400, "Enter a full URL starting with http:// or https://")
    plat = detect(url)
    if not plat: raise HTTPException(422, {"kind": "unsupported", "message": "This platform is not supported. Supported: " + ", ".join(PLATFORMS)})
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "skip_download": True}) as y:
            i = y.extract_info(url, download=False)
    except DownloadError as e:
        k, m = friendly(e); raise HTTPException(422, {"kind": k, "message": m})
    fm = i.get("formats") or []
    audio = max([f.get("filesize") or f.get("filesize_approx") or 0 for f in fm if f.get("vcodec") == "none"] or [0])
    sizes = {}
    for f in fm:
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            s = (f.get("filesize") or f.get("filesize_approx") or 0)
            sizes[h] = max(sizes.get(h, 0), s + (0 if f.get("acodec") not in (None, "none") else audio))
    return {"platform": plat, "title": i.get("title"), "thumb": i.get("thumbnail"), "duration": i.get("duration"),
            "uploader": i.get("uploader"), "heights": sorted(sizes), "sizes": sizes, "audio_size": audio,
            "exts": sorted({f.get("ext") for f in fm if f.get("vcodec") not in (None, "none")} & {"mp4", "webm"}),
            "ffmpeg": HAS_FFMPEG}

@app.post("/api/download")
def download(b: Dl):
    plat = detect(b.url)
    if not plat: raise HTTPException(422, "Unsupported platform")
    if (b.audio or b.format == "mp4" or b.quality != "best") and not HAS_FFMPEG and b.audio:
        raise HTTPException(400, "ffmpeg is required for audio extraction. Install it and restart.")
    if not b.force:
        for j in JOBS.values():
            if j["url"] == b.url and j["status"] in ("completed", "queued", "downloading", "paused") and \
               (j["status"] != "completed" or Path(j.get("path", "")).exists()):
                raise HTTPException(409, "Duplicate: this URL is already downloaded or in progress.")
    job = {"id": uuid.uuid4().hex[:10], "url": b.url, "platform": plat, "title": b.title, "thumb": b.thumb,
           "status": "queued", "progress": 0, "speed": 0, "eta": None, "downloaded": 0, "total": 0, "size": 0,
           "resolution": "audio" if b.audio else ("best" if b.quality == "best" else b.quality + "p"),
           "filename": b.filename or b.title, "created": time.time(), "finished": None, "error": None,
           "opts": {"quality": b.quality, "format": b.format, "audio": b.audio, "filename": b.filename}}
    JOBS[job["id"]] = job; save(job); return job

@app.get("/api/jobs")
def jobs(): return sorted(JOBS.values(), key=lambda j: -j["created"])

@app.post("/api/jobs/{jid}/{action}")
def act(jid: str, action: str):
    j = JOBS.get(jid) or (_ for _ in ()).throw(HTTPException(404, "Not found"))
    if action in ("pause", "cancel"):
        if j["status"] == "downloading": CTL[jid]["stop"] = action
        elif j["status"] == "queued": j["status"] = "paused" if action == "pause" else "cancelled"
    elif action in ("resume", "retry") and j["status"] in ("paused", "failed", "cancelled"):
        j.update(status="queued", error=None, speed=0)
    elif action == "reveal" and j.get("path"):
        p = j["path"]
        if sys.platform == "win32": subprocess.Popen(["explorer", "/select,", p])
        elif sys.platform == "darwin": subprocess.Popen(["open", "-R", p])
        else: subprocess.Popen(["xdg-open", str(Path(p).parent)])
    else: raise HTTPException(400, "Action not valid for this download")
    save(j); return j

@app.delete("/api/jobs/{jid}")
def delete(jid: str, file: bool = False):
    j = JOBS.get(jid)
    if j and j["status"] == "downloading": raise HTTPException(400, "Cancel the download first")
    JOBS.pop(jid, None); DB.execute("DELETE FROM jobs WHERE id=?", (jid,)); DB.commit()
    if j and file and j.get("path") and Path(j["path"]).exists(): Path(j["path"]).unlink()
    return {"ok": True}

@app.get("/api/settings")
def get_settings(): return {**settings(), "ffmpeg": HAS_FFMPEG}

@app.post("/api/settings")
def set_settings(s: dict):
    for k in DEFAULTS:
        if k in s: DB.execute("REPLACE INTO kv VALUES(?,?)", (k, json.dumps(s[k])))
    DB.commit(); Path(settings()["folder"]).mkdir(parents=True, exist_ok=True); return settings()

@app.get("/api/stats")
def stats():
    done = [j for j in JOBS.values() if j["status"] == "completed"]
    f = Path(settings()["folder"]); f.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(f).free
    return {"count": len(done), "bytes": sum(j["size"] for j in done), "free": free,
            "live_speed": sum(j["speed"] for j in JOBS.values() if j["status"] == "downloading"),
            "avg_speed": (sum(j["size"] / max(j["finished"] - j["created"], 1) for j in done) / len(done)) if done else 0}

@app.get("/")
def index(): return FileResponse(BASE / "static" / "index.html")

if __name__ == "__main__":
    import uvicorn, webbrowser
    URL = "http://127.0.0.1:8765"
    cfg = uvicorn.Config(app, host="127.0.0.1", port=8765, log_config=None)
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    time.sleep(1.2)
    try:                                   # native desktop window if pywebview is installed
        import webview
        webview.create_window("Media Downloader Pro", URL, width=1280, height=820, min_size=(900, 600))
        webview.start()
    except ImportError:                    # otherwise open the default browser and keep serving
        webbrowser.open(URL)
        while True: time.sleep(3600)
