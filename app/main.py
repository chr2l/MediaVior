import asyncio
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import sys
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import yt_dlp
from yt_dlp.postprocessor import EmbedThumbnailPP, PostProcessor

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.environ.get("LECOFFRE_DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

APP_NAME = "MediaVior"
GITHUB_URL = "https://github.com/chr2l/MediaVior"
# Mode local : l'appli tourne sur le PC de la personne (lancée par mediavior.py),
# pas sur un serveur. Ajoute « Ouvrir le dossier » et « Quitter », et protège l'API
# contre les autres sites ouverts dans le navigateur.
LOCAL_MODE = os.environ.get("MEDIAVIOR_LOCAL") == "1"
QUIT_HOOK = None  # fourni par mediavior.py pour arrêter le serveur proprement

# Change à chaque démarrage : force le navigateur à recharger CSS/JS après une mise à jour
ASSET_VERSION = str(int(time.time()))
# Date de la dernière mise à jour de l'appli : le fichier de code le plus récent de l'image
UPDATED_AT = int(max(
    (p.stat().st_mtime for p in BASE_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts),
    default=time.time(),
))

META_FILE = "meta.json"
ITEM_ID = re.compile(r"^[0-9a-f]{32}$")
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".opus", ".ogg", ".flac", ".aac"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_CONTAINERS = {"original", "mp4", "mov"}
AUDIO_CONTAINERS = {"original", "mp3", "flac", "wav"}
# Formats où yt-dlp sait intégrer une pochette (le WebM n'en accepte pas)
COVER_EXTS = {"mp3", "m4a", "opus", "ogg", "flac", "mp4", "m4v", "mkv", "mka"}
YTDLP_CHECK_EVERY = 12 * 3600  # vérification d'une nouvelle version de yt-dlp
IGNORED_SUFFIXES = {".part", ".ytdl", ".temp", ".tmp"}
ACTIVE_STATUSES = {"queued", "downloading", "converting", "processing"}
TESSERACT = os.environ.get("TESSERACT_BIN", "tesseract")
SONS_FILE = DOWNLOAD_DIR / ".liste-sons.json"
SONS_LOCK = threading.Lock()  # la liste est aussi modifiée par le job, dans un autre thread
MAX_SCREEN_BYTES = 20 * 1024 * 1024
MAX_SON_DURATION = 15 * 60  # au-delà, c'est sûrement un mix ou un album entier

# Suivi des jobs en mémoire (suffisant pour un outil mono-utilisateur auto-hébergé).
# Les fichiers terminés, eux, sont retrouvés sur le disque grâce à meta.json.
JOBS: Dict[str, dict] = {}
PROCS: Dict[str, subprocess.Popen] = {}  # ffmpeg des montages en cours, pour pouvoir les annuler
QUEUE: "asyncio.Queue[str]" = asyncio.Queue()


class JobCancelled(Exception):
    pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _cleanup_unfinished()
    worker = asyncio.create_task(_worker())
    updater = asyncio.create_task(_ytdlp_updater())
    yield
    worker.cancel()
    updater.cancel()


app = FastAPI(title=APP_NAME, lifespan=lifespan)
# L'extension de navigateur (dossier extension/) appelle l'API depuis sa propre origine
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome|moz)-extension://[a-z0-9-]+$",
    allow_methods=["*"],
    allow_headers=["*"],
)


if LOCAL_MODE:
    @app.middleware("http")
    async def _local_guard(request: Request, call_next):
        """En local, n'importe quel site ouvert dans le navigateur peut viser 127.0.0.1.
        On n'accepte que les requêtes adressées à localhost (contre le « DNS rebinding »)
        et, pour les actions, venant de l'appli elle-même ou de l'extension."""
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            return JSONResponse({"detail": "Adresse non autorisée."}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            o = urlparse(origin)
            same = o.hostname in ("127.0.0.1", "localhost", "::1") and o.port == request.url.port
            if not same and not re.match(r"^(chrome|moz)-extension://[a-z0-9-]+$", origin):
                return JSONResponse({"detail": "Requête refusée."}, status_code=403)
        return await call_next(request)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    mode: Literal["video", "audio"]
    quality: Optional[str] = None  # hauteur max pour la vidéo (ex: "2160")
    # "original" = tel que le site le fournit, sans réencodage (vidéo comme audio)
    container: Literal["original", "mp4", "mov", "mp3", "flac", "wav"]
    audio_quality: Optional[str] = None  # MP3 uniquement : "320", "192", "128" ("0" = VBR V0)
    title: Optional[str] = None
    thumbnail: Optional[str] = None


class LinksRequest(BaseModel):
    """Plusieurs liens, un même format : tout finit dans un seul zip."""
    urls: list[str] = Field(min_length=1, max_length=100)
    mode: Literal["video", "audio"]
    quality: Optional[str] = None
    container: Literal["original", "mp4", "mov", "mp3", "flac", "wav"]
    audio_quality: Optional[str] = None


class SonsAddRequest(BaseModel):
    queries: list[str]


class SonUpdateRequest(BaseModel):
    query: str


class SonPickRequest(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = ""


class SonsFetchRequest(BaseModel):
    container: Literal["mp3", "wav"] = "mp3"
    audio_quality: Optional[Literal["0", "320", "192", "128"]] = None


class EditRequest(BaseModel):
    start: float
    end: float
    fade_in: float = 0
    fade_out: float = 0
    gain: float = 0  # en dB
    normalize: bool = False
    mute: bool = False
    format: Optional[Literal["mp4", "mov", "mp3", "wav"]] = None  # None = même format que la source
    fast: bool = False  # coupe sans réencodage


# ---------------------------------------------------------------------------
# Mise à jour de yt-dlp
# ---------------------------------------------------------------------------
# Les sites changent souvent leur structure : un yt-dlp périmé finit par échouer.
# Le conteneur met yt-dlp à jour à chaque démarrage (entrypoint.sh). Ici, on vérifie
# régulièrement si une nouvelle version est sortie et, dès que la file est vide, on
# s'arrête proprement : Docker relance le conteneur, qui installe la nouvelle version.

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def _latest_ytdlp() -> Optional[str]:
    with urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=20) as resp:
        return json.load(resp)["info"]["version"]


async def _ytdlp_updater() -> None:
    if os.environ.get("LECOFFRE_AUTO_UPDATE") != "1":  # activé dans l'image Docker uniquement
        return
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(YTDLP_CHECK_EVERY)
        try:
            latest = await loop.run_in_executor(None, _latest_ytdlp)
        except Exception:
            continue
        if not latest or _version_tuple(latest) <= _version_tuple(yt_dlp.version.__version__):
            continue
        while any(j["status"] in ACTIVE_STATUSES for j in JOBS.values()):
            await asyncio.sleep(60)
        print(f"yt-dlp {latest} disponible : redémarrage pour mise à jour", file=sys.stderr, flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        return


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "v": ASSET_VERSION, "ytdlp": yt_dlp.version.__version__, "updated": UPDATED_AT,
        "local": LOCAL_MODE, "github": GITHUB_URL, "folder": str(DOWNLOAD_DIR),
    })


@app.get("/legal")
async def legal(request: Request):
    return templates.TemplateResponse(request, "legal.html", {"v": ASSET_VERSION, "github": GITHUB_URL})


# ---------------------------------------------------------------------------
# Version locale (PC) : prompt d'installation, dossier, arrêt
# ---------------------------------------------------------------------------

def _prompt_file() -> Optional[Path]:
    # app/ en local (le dépôt entier est là), /app dans l'image Docker
    for p in (BASE_DIR.parent / "PROMPT.md", BASE_DIR / "PROMPT.md"):
        if p.is_file():
            return p
    return None


@app.get("/api/ping")
async def ping():
    return {"app": "mediavior", "local": LOCAL_MODE}


@app.get("/api/prompt", response_class=PlainTextResponse)
async def install_prompt():
    """Le prompt à coller dans une IA pour installer MediaVior sur son propre PC."""
    p = _prompt_file()
    if not p:
        raise HTTPException(status_code=404, detail="Prompt introuvable.")
    return p.read_text(encoding="utf-8")


def _local_only() -> None:
    if not LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Disponible seulement dans la version PC.")


@app.post("/api/local/open-folder")
async def open_folder():
    _local_only()
    target = str(DOWNLOAD_DIR)
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


@app.post("/api/local/quit")
async def quit_app():
    _local_only()
    if QUIT_HOOK:
        asyncio.get_running_loop().call_later(0.3, QUIT_HOOK)
    return {"ok": True}


@app.get("/edit/{item_id}")
async def editor(request: Request, item_id: str):
    _item_dir(item_id)
    return templates.TemplateResponse(request, "editor.html", {"v": ASSET_VERSION, "item_id": item_id})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(BASE_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # Servi à la racine pour que le service worker contrôle toute l'appli
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# Sécurité des liens et messages d'erreur
# ---------------------------------------------------------------------------

async def _safe_url(raw: str) -> str:
    """Refuse les liens qui pointent vers le serveur lui-même ou le réseau local."""
    url = raw.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Colle un lien.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Lien invalide : seuls les liens http(s) sont acceptés.")

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, None)
    except (socket.gaierror, UnicodeError):
        raise HTTPException(status_code=400, detail="Adresse introuvable : vérifie le lien.")

    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise HTTPException(
                status_code=400,
                detail="Les adresses locales ou internes (localhost, 10.x, 192.168.x…) ne sont pas autorisées.",
            )
    return url


ERROR_PATTERNS = [
    (r"private video|video is private", "Cette vidéo est privée : seul son propriétaire peut la voir."),
    (r"confirm your age|age[- ]restricted|inappropriate for some users",
     "Ce média est soumis à une restriction d'âge et nécessite un compte connecté."),
    (r"not available in your country|blocked it in your country|geo.?restrict|not available in your region|"
     r"not available from your location",
     "Ce média n'est pas disponible depuis le pays du serveur."),
    (r"only works when logged.in|login required|log in to|account credentials|use --cookies",
     "Ce média n'est accessible qu'avec un compte connecté sur le site."),
    (r"not a bot|sign in to confirm",
     "Le site demande une vérification anti-robot pour ce serveur. Réessaie plus tard ou mets à jour yt-dlp."),
    (r"members[- ]only|join this channel", "Ce média est réservé aux membres de la chaîne."),
    (r"premieres in|live event will begin|is upcoming", "Ce média n'a pas encore été diffusé."),
    (r"\bdrm\b", "Ce média est protégé par DRM et ne peut pas être sauvegardé."),
    (r"video (is )?unavailable|has been removed|no longer available|does not exist|http error 404|"
     r"account.*terminated",
     "Ce média n'existe plus ou a été retiré."),
    (r"unsupported url", "Ce site n'est pas pris en charge, ou le lien ne pointe pas vers un média."),
    (r"http error 429|too many requests", "Le site limite les requêtes : réessaie dans quelques minutes."),
    (r"http error 403|forbidden",
     "Le site a refusé l'accès (403). yt-dlp se met à jour tout seul : réessaie plus tard."),
    (r"unable to extract|nsig|signature|could not find .*(player|js)",
     "Le site a changé sa structure. yt-dlp se met à jour tout seul : réessaie plus tard."),
    (r"requested format is not available", "Ce format n'est pas disponible pour ce média : essaie une autre qualité."),
    (r"unable to download webpage|name or service not known|timed out|connection (refused|reset)",
     "Impossible de joindre le site. Vérifie le lien ou la connexion du serveur."),
    (r"no space left", "Le disque du serveur est plein."),
    (r"ffmpeg is not installed|ffmpeg not found", "ffmpeg est introuvable sur le serveur."),
    (r"ffmpeg|postprocess", "La conversion a échoué (ffmpeg)."),
]


def _humanize_error(exc: Exception) -> str:
    raw = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    for pattern, message in ERROR_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            return message
    # Cas inconnu : on garde la première ligne, sans les préfixes techniques de yt-dlp
    line = next((l for l in raw.splitlines() if l.strip()), "Erreur inconnue.")
    line = re.sub(r"^(ERROR:\s*)?(\[[^\]]+\]\s*)?([\w-]+:\s)?", "", line.strip())
    return line[:200] or "Erreur inconnue."


# ---------------------------------------------------------------------------
# Bibliothèque (fichiers sur le disque)
# ---------------------------------------------------------------------------

def _read_meta(d: Path) -> dict:
    try:
        return json.loads((d / META_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(d: Path, meta: dict) -> None:
    tmp = d / ".meta.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    tmp.replace(d / META_FILE)


def _media_file(d: Path) -> Optional[Path]:
    candidates = [
        p for p in d.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name != META_FILE
        and p.suffix.lower() not in IGNORED_SUFFIXES
    ]
    return max(candidates, key=lambda p: p.stat().st_size, default=None)


def _item_view(d: Path) -> Optional[dict]:
    meta = _read_meta(d)
    if meta and meta.get("status") != "done":
        return None
    media = _media_file(d)
    if not media:
        return None
    st = media.stat()
    return {
        "id": d.name,
        "title": meta.get("title") or media.stem,
        "filename": media.name,
        "ext": media.suffix.lstrip(".").lower(),
        "size": st.st_size,
        "created": meta.get("created") or st.st_mtime,
        "thumbnail": meta.get("thumbnail"),
        "source": meta.get("source"),
        "duration": meta.get("duration"),
        "mode": "archive" if media.suffix.lower() == ".zip"
        else "audio" if media.suffix.lower() in AUDIO_EXTS else "video",
        "edited": bool(meta.get("parent")),
        "count": meta.get("count"),  # nombre de fichiers dans un zip
    }


def _item_dir(item_id: str) -> Path:
    if not ITEM_ID.match(item_id):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    d = DOWNLOAD_DIR / item_id
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return d


def _item_or_404(item_id: str) -> dict:
    item = _item_view(_item_dir(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Fichier pas encore prêt")
    return item


def _cleanup_unfinished() -> None:
    """Au démarrage, supprime les dossiers de jobs interrompus par un redémarrage."""
    for d in DOWNLOAD_DIR.iterdir():
        if d.is_dir() and ITEM_ID.match(d.name):
            meta = _read_meta(d)
            if meta and meta.get("status") != "done":
                shutil.rmtree(d, ignore_errors=True)
    for z in DOWNLOAD_DIR.glob(".selection-*.zip"):  # zips de sélection pas encore effacés
        z.unlink(missing_ok=True)


@app.get("/api/library")
async def library():
    items = [
        item for d in DOWNLOAD_DIR.iterdir()
        if d.is_dir() and ITEM_ID.match(d.name) and (item := _item_view(d))
    ]
    items.sort(key=lambda i: i["created"], reverse=True)
    return items


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height:stream_disposition=attached_pic",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    # Les pochettes intégrées aux MP3 apparaissent comme des flux vidéo : on les ignore
    video = [s for s in streams if s.get("codec_type") == "video"
             and not (s.get("disposition") or {}).get("attached_pic")]
    return {
        "duration": float((data.get("format") or {}).get("duration") or 0),
        "has_video": bool(video),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video[0].get("width") if video else None,
        "height": video[0].get("height") if video else None,
    }


@app.get("/api/library/{item_id}")
async def library_item(item_id: str):
    item = _item_or_404(item_id)
    media = DOWNLOAD_DIR / item_id / item["filename"]
    try:
        probe = await asyncio.get_running_loop().run_in_executor(None, _probe, media)
    except Exception:
        raise HTTPException(status_code=500, detail="Impossible de lire ce fichier (ffprobe).")
    return {**item, **probe}


@app.delete("/api/library/{item_id}")
async def delete_item(item_id: str):
    d = _item_dir(item_id)
    job = JOBS.get(item_id)
    if job and job["status"] in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Ce fichier est encore en cours de traitement.")
    shutil.rmtree(d, ignore_errors=True)
    JOBS.pop(item_id, None)
    return {"ok": True}


@app.get("/api/file/{item_id}")
async def get_file(item_id: str, inline: bool = False):
    item = _item_or_404(item_id)
    return FileResponse(
        DOWNLOAD_DIR / item_id / item["filename"],
        filename=item["filename"],
        content_disposition_type="inline" if inline else "attachment",
    )


def _zip_items(items: list) -> Path:
    fd, tmp = tempfile.mkstemp(prefix=".selection-", suffix=".zip", dir=DOWNLOAD_DIR)
    os.close(fd)
    used = set()
    # Les médias sont déjà compressés : on les range tels quels (rapide, même taille)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for item in items:
            name, n = item["filename"], 2
            while name.casefold() in used:
                name = f"{Path(item['filename']).stem} ({n}){Path(item['filename']).suffix}"
                n += 1
            used.add(name.casefold())
            zf.write(DOWNLOAD_DIR / item["id"] / item["filename"], name)
    return Path(tmp)


@app.get("/api/files.zip")
async def get_files_zip(ids: str):
    """Plusieurs fichiers de la bibliothèque d'un coup, dans un seul zip."""
    wanted = list(dict.fromkeys(i for i in ids.split(",") if i))
    if not wanted or len(wanted) > 500:
        raise HTTPException(status_code=400, detail="Sélection vide ou trop grande.")
    items = [_item_or_404(i) for i in wanted]
    tmp = await asyncio.get_running_loop().run_in_executor(None, _zip_items, items)
    return FileResponse(
        tmp,
        filename=f"{APP_NAME} - {len(items)} fichiers.zip",
        background=BackgroundTask(tmp.unlink, missing_ok=True),
    )


def _make_waveform(media: Path, png: Path) -> bool:
    tmp = png.with_name(".waveform-tmp.png")
    result = subprocess.run(
        [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(media),
         "-filter_complex", "aformat=channel_layouts=mono,showwavespic=s=1600x200:scale=sqrt:colors=0x3B8CC2",
         "-frames:v", "1", str(tmp)],
        capture_output=True, timeout=600,
    )
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(png)
    return True


@app.get("/api/library/{item_id}/waveform")
async def waveform(item_id: str):
    item = _item_or_404(item_id)
    d = DOWNLOAD_DIR / item_id
    png = d / ".waveform.png"
    if not png.exists():
        ok = await asyncio.get_running_loop().run_in_executor(None, _make_waveform, d / item["filename"], png)
        if not ok:
            raise HTTPException(status_code=404, detail="Pas de piste audio")
    return FileResponse(png, media_type="image/png")


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------

def _extract_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",  # une playlist répond vite au lieu d'analyser chaque vidéo
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _format_size(f: dict, duration: Optional[float]) -> Optional[float]:
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return size


def _size_estimates(formats: list, duration: Optional[float]):
    """Taille approximative par résolution (vidéo + meilleure piste audio)."""
    best_audio = max(
        (s for f in formats
         if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
         and (s := _format_size(f, duration))),
        default=0,
    )
    by_height: Dict[int, Optional[float]] = {}
    for f in formats:
        h = f.get("height")
        if not h or f.get("vcodec") in (None, "none"):
            continue
        size = _format_size(f, duration)
        total = None
        if size:
            total = size if f.get("acodec") not in (None, "none") else size + best_audio
        if total and (by_height.get(h) is None or total > by_height[h]):
            by_height[h] = total
        else:
            by_height.setdefault(h, None)
    video = [{"height": h, "size": by_height[h]} for h in sorted(by_height, reverse=True)]
    return video, best_audio or None


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest):
    url = await _safe_url(payload.url)
    try:
        info = await asyncio.get_running_loop().run_in_executor(None, _extract_info, url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_humanize_error(exc))

    if info.get("_type") == "playlist":
        raise HTTPException(
            status_code=400,
            detail="C'est une playlist : colle plutôt les liens des médias un par un (plusieurs à la fois, c'est possible).",
        )

    duration = info.get("duration")
    video_formats, audio_size = _size_estimates(info.get("formats") or [], duration)
    return {
        "url": url,
        "title": info.get("title") or "Média sans titre",
        "thumbnail": info.get("thumbnail"),
        "duration": duration,
        "source": info.get("extractor_key") or info.get("extractor"),
        "video_formats": video_formats,
        "audio_size": audio_size,
    }


# ---------------------------------------------------------------------------
# File d'attente
# ---------------------------------------------------------------------------

def _public(job: dict) -> dict:
    view = {k: v for k, v in job.items() if not k.startswith("_")}
    if job["status"] == "queued":
        queued = [j for j in JOBS.values() if j["status"] == "queued"]
        view["position"] = queued.index(job) + 1
    return view


def _new_job(kind: str, title: str, thumbnail: Optional[str], payload: dict) -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "progress": 0,
        "title": title,
        "thumbnail": thumbnail,
        "error": None,
        "speed": None,
        "eta": None,
        "filename": None,
        "created": time.time(),
        "finished": None,
        "_cancel": False,
        "_payload": payload,
    }
    JOBS[job_id] = job
    return job


async def _worker() -> None:
    """Traite les jobs un par un, dans l'ordre d'arrivée."""
    loop = asyncio.get_running_loop()
    while True:
        job_id = await QUEUE.get()
        job = JOBS.get(job_id)
        if not job or job["status"] != "queued":  # annulé pendant l'attente
            continue
        runner = {"download": _download_sync, "edit": _edit_sync, "sons": _sons_sync,
                  "links": _links_sync}[job["kind"]]
        try:
            await loop.run_in_executor(None, runner, job)
            if job["_cancel"]:
                raise JobCancelled()
            job.update(status="done", progress=100, speed=None, eta=None)
        except Exception as exc:
            if job["_cancel"] or isinstance(exc, JobCancelled):
                job["status"] = "cancelled"
            else:
                job.update(status="error", error=_humanize_error(exc))
            shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)
        finally:
            job["finished"] = time.time()
            PROCS.pop(job_id, None)


@app.get("/api/jobs")
async def list_jobs():
    # Les jobs terminés depuis un moment sont dans la bibliothèque : inutile de les garder ici
    now = time.time()
    for job_id in [i for i, j in JOBS.items() if j["status"] == "done" and now - j["finished"] > 300]:
        JOBS.pop(job_id, None)
    return [_public(j) for j in JOBS.values()]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return _public(job)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if job["status"] == "queued":
        job.update(status="cancelled", finished=time.time())
        shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)
    elif job["status"] in ACTIVE_STATUSES:
        job["_cancel"] = True
        proc = PROCS.get(job_id)
        if proc:
            proc.kill()
    return _public(job)


@app.delete("/api/jobs/{job_id}")
async def dismiss_job(job_id: str):
    job = JOBS.get(job_id)
    if job and job["status"] in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Annule le job avant de le retirer.")
    JOBS.pop(job_id, None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

# Mentions qui encombrent les titres YouTube : « (Official Video) », « [Clip officiel] », « (Lyrics) »…
# « (Live) », « (Remix) » ou « (Remastered 2011) » font partie du titre et sont gardés.
_TITLE_NOISE = re.compile(
    r"\s*[(\[][^)\]]*\b(?:official|officiel(?:le)?|clip|video|vidéo|audio|lyrics?|paroles|visuali[sz]er"
    r"|hd|hq|4k|mv)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)
_TITLE_TAIL = re.compile(r"\s*[|｜]\s*.*\b(?:official|officiel|clip|video|vidéo|audio|lyrics?|paroles)\b.*$", re.IGNORECASE)
_TITLE_SPLIT = re.compile(r"^(.+?)\s+[-–—]\s+(.+)$")
_CHANNEL_NOISE = re.compile(r"(?:\s*-\s*topic|vevo|\s+official|\s+officiel)$", re.IGNORECASE)


def _clean_title(title: str) -> str:
    cleaned = _TITLE_TAIL.sub("", _TITLE_NOISE.sub("", title)).strip(" -–—|")
    return cleaned or title


def _clean_channel(name: str) -> str:
    return _CHANNEL_NOISE.sub("", name.strip()).strip() or name


def _year(info: dict) -> Optional[str]:
    for key in ("release_year", "release_date", "upload_date"):
        value = str(info.get(key) or "")
        if re.match(r"^\d{4}", value):
            return value[:4]
    return None


def _file_tags(info: dict, music: bool) -> dict:
    """Propriétés écrites dans le fichier (titre, artiste, album, année, genre…).

    yt-dlp remplit déjà ces champs, mais pour une vidéo YouTube ordinaire l'artiste est la chaîne,
    le titre traîne « (Official Video) », la date est illisible (AAAAMMJJ) et le genre est la liste
    des mots-clés. On corrige ici ; ce qui est renvoyé remplace les valeurs de yt-dlp.
    """
    title = info.get("title") or ""
    channel = _clean_channel(info.get("artist") or info.get("creator") or info.get("channel")
                             or info.get("uploader") or "")
    artists = [a for a in (info.get("artists") or []) if a] or ([info["artist"]] if info.get("artist") else [])
    genres = [g for g in (info.get("genres") or []) if g] or ([info["genre"]] if info.get("genre") else [])
    tags = {}

    if music:
        track = info.get("track")
        artist = ", ".join(artists)
        if not track:
            track = _clean_title(title)
            split = _TITLE_SPLIT.match(track)
            if split and not artist:
                artist, track = split.group(1).strip(), split.group(2).strip()
        artist = artist or channel
        tags.update(title=track, artist=artist, album_artist=artists[0] if artists else artist)
        if info.get("album"):
            tags["album"] = info["album"]
        tags["date"] = _year(info) or ""
        tags["genre"] = ", ".join(genres)  # vide plutôt que les mots-clés YouTube
        if info.get("composers") or info.get("composer"):
            tags["composer"] = ", ".join(info.get("composers") or [info["composer"]])
    else:
        upload = str(info.get("upload_date") or "")
        tags.update(title=title, artist=channel)
        tags["date"] = (f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}" if re.fullmatch(r"\d{8}", upload)
                        else _year(info) or "")
        tags["genre"] = ", ".join(genres or (info.get("categories") or [])[:1])
    if info.get("track_number"):
        tags["track"] = str(info["track_number"])
    tags["comment"] = info.get("webpage_url") or ""
    tags["encoded_by"] = APP_NAME
    return tags


class _FileTags(PostProcessor):
    """Prépare les propriétés du fichier ; FFmpegMetadata les écrit ensuite (champs meta_*)."""

    def __init__(self, downloader=None, music: bool = False):
        super().__init__(downloader)
        self._music = music

    def run(self, info):
        try:
            # Un clip musical téléchargé en vidéo est tagué comme un morceau
            music = self._music or bool(info.get("track")) or "Music" in (info.get("categories") or [])
            for key, value in _file_tags(info, music).items():
                info[f"meta_{key}"] = value
        except Exception as exc:  # des propriétés incomplètes ne valent pas un échec
            self.report_warning(f"propriétés du fichier incomplètes : {exc}")
        return [], info


def _tag_options(ydl_opts: dict, postprocessors: list, final_ext: Optional[str]) -> None:
    """Ajoute l'écriture des propriétés du fichier aux options yt-dlp."""
    postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if final_ext == "mp3":
        # ID3v2.3 : la version que l'explorateur Windows et la plupart des lecteurs lisent sans souci
        ydl_opts["postprocessor_args"] = {"ffmpegmetadata": ["-id3v2_version", "3"]}


def _embed_cover_mp4(media: Path, image: Path) -> None:
    """Pochette d'un MP4/MOV produit par la conversion (la pochette du MKV intermédiaire est perdue)."""
    from mutagen.mp4 import MP4, MP4Cover
    fmt = MP4Cover.FORMAT_PNG if image.suffix.lower() == ".png" else MP4Cover.FORMAT_JPEG
    tagged = MP4(media)
    if tagged.tags is None:
        tagged.add_tags()
    tagged.tags["covr"] = [MP4Cover(image.read_bytes(), imageformat=fmt)]
    tagged.save()


class _CoverArt(EmbedThumbnailPP):
    """Pochette intégrée au fichier quand le format le permet, sans jamais faire échouer le téléchargement."""

    def run(self, info):
        if info.get("ext") not in COVER_EXTS or not info.get("thumbnails"):
            return [], info
        try:
            return super().run(info)
        except Exception as exc:
            self.report_warning(f"pochette non intégrée : {exc}")
            return [], info


def _stream_codecs(path: Path) -> tuple:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    streams = json.loads(out.stdout or "{}").get("streams") or []
    first = lambda kind: next((s for s in streams if s.get("codec_type") == kind), None)
    return first("video"), first("audio")


def _make_compatible(job: dict, src: Path, container: str, duration: Optional[float]) -> None:
    """Produit un MP4/MOV H.264 + AAC, lisible partout. Copie simple si les codecs conviennent déjà."""
    video, audio = _stream_codecs(src)
    out = src.with_name(f"{src.stem}.{container}")
    if out == src:
        out = src.with_name(f"{src.stem}.tmp.{container}")
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]
    if video and video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p":
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    if audio and audio.get("codec_name") == "aac":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "256k"]
    cmd += ["-movflags", "+faststart", str(out)]

    job.update(status="converting", speed=None, eta=None, progress=0, encoding=True)
    _run_ffmpeg(job, cmd, duration, src.parent / ".ffmpeg.log", "La conversion a échoué")
    src.unlink(missing_ok=True)
    if out.name.endswith(f".tmp.{container}"):
        out = out.replace(src.with_name(f"{src.stem}.{container}"))


def _run_ffmpeg(job: dict, cmd: list, total: Optional[float], log_path: Path, failure: str) -> None:
    """Lance ffmpeg en suivant sa progression ; annulable via PROCS."""
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
        PROCS[job["id"]] = proc
        if job["_cancel"]:
            proc.kill()
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if total and key in ("out_time_us", "out_time_ms") and value.isdigit():
                job["progress"] = round(min(99.0, int(value) / 1e6 / total * 100), 1)
        returncode = proc.wait()
        PROCS.pop(job["id"], None)

    if job["_cancel"]:
        raise JobCancelled()
    if returncode != 0:
        detail = log_path.read_text("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(f"{failure} : " + (detail[-1] if detail else f"code {returncode}"))
    log_path.unlink(missing_ok=True)


@app.post("/api/download")
async def start_download(payload: DownloadRequest):
    url = await _safe_url(payload.url)
    _check_format(payload.mode, payload.container, payload.quality, payload.audio_quality)

    data = payload.model_dump()
    data["url"] = url
    job = _new_job("download", payload.title or url, payload.thumbnail, data)
    job_dir = DOWNLOAD_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {
        "status": "queued", "kind": "download", "url": url, "title": payload.title,
        "thumbnail": payload.thumbnail, "created": job["created"],
    })
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _fetch_media(job: dict, p: dict, url: str, job_dir: Path, index: int = 0, count: int = 1) -> dict:
    """Télécharge un média dans job_dir avec les options p. index/count : place dans un lot de liens."""
    outtmpl = str(job_dir / "%(title).150s.%(ext)s")
    parts_done = 0
    single = count == 1

    def progress_hook(d: dict) -> None:
        nonlocal parts_done
        if job["_cancel"]:
            raise JobCancelled()
        info = d.get("info_dict") or {}
        if single and job["title"] == url and info.get("title"):
            job["title"] = info["title"]
            job["thumbnail"] = job["thumbnail"] or info.get("thumbnail")
        # Vidéo + audio séparés = deux fichiers téléchargés à la suite : une seule barre pour les deux
        parts = len(info.get("requested_formats") or []) or 1
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            fraction = (d.get("downloaded_bytes") or 0) / total if total else 0
            done = (parts_done + fraction) / parts
            job["progress"] = round(min(100, (index + done) / count * 100), 1)
            job.update(status="downloading", speed=d.get("speed"), eta=d.get("eta") if single else None)
        elif d["status"] == "finished":
            parts_done += 1
            if single and parts_done >= parts:
                job.update(status="converting", speed=None, eta=None)

    def postprocessor_hook(d: dict) -> None:
        if job["_cancel"]:
            raise JobCancelled()
        if single and d["status"] == "started":
            job.update(status="converting", speed=None, eta=None)

    ydl_opts = {
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    container = p["container"]
    postprocessors = []
    # Pochette téléchargée (sauf WAV, qui n'en accepte pas), puis intégrée au fichier
    if container != "wav":
        ydl_opts["writethumbnail"] = True
        postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})

    if p["mode"] == "audio":
        ydl_opts["format"] = "bestaudio/best"
        postprocessors.insert(0, {
            "key": "FFmpegExtractAudio",
            # "best" garde le codec de la source : simple changement de conteneur, aucune perte
            "preferredcodec": "best" if container == "original" else container,
            "preferredquality": p["audio_quality"] or "320",
        })
    else:
        quality = p["quality"]
        if quality:
            ydl_opts["format"] = f"bv*[height<={quality}]+ba/b[height<={quality}]/bv*+ba/b"
        else:
            ydl_opts["format"] = "bv*+ba/b"
        if container == "original":
            # Meilleure qualité (souvent VP9/AV1 + Opus) : conteneur choisi selon les codecs, sans réencodage
            ydl_opts["merge_output_format"] = "webm/mp4/mkv"
        else:
            # À résolution égale, préférer ce qui se lit partout (H.264/AAC, SDR) : évite souvent la conversion
            ydl_opts["format_sort"] = ["res", "fps", "+hdr", "vcodec:h264", "acodec:aac"]
            ydl_opts["merge_output_format"] = "mkv"  # étape intermédiaire, accepte tous les codecs
    # Titre, artiste, album, année, genre… écrits dans le fichier
    _tag_options(ydl_opts, postprocessors, container if p["mode"] == "audio" else None)
    ydl_opts["postprocessors"] = postprocessors
    # En vidéo convertie, la pochette est ajoutée après la conversion en MP4/MOV
    converted = p["mode"] == "video" and container != "original"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(_FileTags(ydl, music=p["mode"] == "audio"), when="pre_process")
        if ydl_opts.get("writethumbnail") and not converted:
            ydl.add_post_processor(_CoverArt(ydl), when="post_process")
        info = ydl.extract_info(url, download=True) or {}

    if job["_cancel"]:
        raise JobCancelled()
    if converted:
        source = _media_file(job_dir)
        if not source:
            raise RuntimeError("Aucun fichier n'a été produit.")
        _make_compatible(job, source, container, info.get("duration"))
        media = _media_file(job_dir)
        cover = next((f for f in job_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS), None)
        if media and cover:
            try:
                _embed_cover_mp4(media, cover)
            except Exception:
                pass  # une pochette manquante ne vaut pas un échec
    for leftover in job_dir.iterdir():  # pochettes non intégrées
        if leftover.suffix.lower() in IMAGE_EXTS:
            leftover.unlink(missing_ok=True)
    return info


def _download_sync(job: dict) -> None:
    p = job["_payload"]
    job_dir = DOWNLOAD_DIR / job["id"]
    info = _fetch_media(job, p, p["url"], job_dir)
    result_file = _media_file(job_dir)
    if not result_file:
        raise RuntimeError("Aucun fichier n'a été produit.")

    job["title"] = info.get("title") or job["title"]
    job["filename"] = result_file.name
    _write_meta(job_dir, {
        "status": "done",
        "kind": "download",
        "url": p["url"],
        "title": job["title"],
        "thumbnail": info.get("thumbnail") or job["thumbnail"],
        "duration": info.get("duration"),
        "source": info.get("extractor_key") or info.get("extractor"),
        "created": job["created"],
    })


def _check_format(mode: str, container: str, quality: Optional[str], audio_quality: Optional[str]) -> None:
    if container not in (VIDEO_CONTAINERS if mode == "video" else AUDIO_CONTAINERS):
        raise HTTPException(status_code=400, detail="Format incompatible avec le type de média.")
    if quality and not quality.isdigit():
        raise HTTPException(status_code=400, detail="Qualité invalide.")
    if audio_quality not in (None, "0", "320", "192", "128"):
        raise HTTPException(status_code=400, detail="Qualité audio invalide.")


@app.post("/api/links")
async def start_links(payload: LinksRequest):
    _check_format(payload.mode, payload.container, payload.quality, payload.audio_quality)
    urls = []
    for raw in dict.fromkeys(u.strip() for u in payload.urls if u.strip()):
        try:
            urls.append(await _safe_url(raw))
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=f"{raw} : {exc.detail}")
    if not urls:
        raise HTTPException(status_code=400, detail="Aucun lien.")
    n = len(urls)
    title = f"Plusieurs liens · {n} lien{'s' if n > 1 else ''}"
    data = {**payload.model_dump(), "urls": urls}
    job = _new_job("links", title, None, data)
    job.update(step=None, found=0, missing=0)
    job_dir = DOWNLOAD_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {"status": "queued", "kind": "links", "title": title, "created": job["created"]})
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _links_sync(job: dict) -> None:
    """Télécharge chaque lien dans son sous-dossier, puis range tout dans un zip."""
    p = job["_payload"]
    job_dir = DOWNLOAD_DIR / job["id"]
    work = job_dir / ".pistes"
    work.mkdir(exist_ok=True)
    urls = p["urls"]
    total = len(urls)
    found: List[Path] = []
    errors: List[str] = []

    for index, url in enumerate(urls):
        if job["_cancel"]:
            raise JobCancelled()
        job.update(status="downloading", step=f"{index + 1}/{total}", speed=None, eta=None,
                   encoding=False, progress=round(index / total * 100, 1))
        target = work / f"{index:03d}"
        target.mkdir(exist_ok=True)
        try:
            _fetch_media(job, p, url, target, index, total)
            media = _media_file(target)
            if media:
                found.append(media)
            else:
                errors.append(url)
        except JobCancelled:
            raise
        except Exception:
            if job["_cancel"]:
                raise JobCancelled()
            errors.append(url)
        job.update(found=len(found), missing=len(errors))

    if job["_cancel"]:
        raise JobCancelled()
    if not found:
        raise RuntimeError("Aucun des liens n'a pu être téléchargé.")

    job.update(status="converting", step=None, speed=None, encoding=False)
    stamp = time.strftime("%Y-%m-%d %Hh%M", time.localtime(job["created"]))
    zip_path = job_dir / f"{APP_NAME} {stamp}.zip"
    used = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for media in found:
            name, n = media.name, 2
            while name.casefold() in used:
                name = f"{media.stem} ({n}){media.suffix}"
                n += 1
            used.add(name.casefold())
            zf.write(media, name)
    shutil.rmtree(work, ignore_errors=True)

    count = len(found)
    job["title"] = f"Plusieurs liens · {count} fichier{'s' if count > 1 else ''}"
    if errors:
        job["title"] += f" ({len(errors)} raté{'s' if len(errors) > 1 else ''})"
    job["filename"] = zip_path.name
    _write_meta(job_dir, {
        "status": "done",
        "kind": "links",
        "title": job["title"],
        "count": count,
        "failed": errors,
        "created": job["created"],
    })


# ---------------------------------------------------------------------------
# Éditeur
# ---------------------------------------------------------------------------

AUDIO_CODECS = {
    "mp4": ["-c:a", "aac", "-b:a", "192k"],
    "mov": ["-c:a", "aac", "-b:a", "192k"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
    "wav": ["-c:a", "pcm_s16le"],
}


def _build_edit_cmd(p: dict, src: Path, out: Path) -> list:
    start, end = p["start"], p["end"]
    dur = end - start
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats",
           "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}"]

    if p["fast"]:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        if p["mute"]:
            cmd += ["-an"]
        return cmd + [str(out)]

    fmt, fi, fo = p["format"], p["fade_in"], p["fade_out"]

    if p["has_video"] and fmt in ("mp4", "mov"):
        vf = []
        if fi:
            vf.append(f"fade=t=in:st=0:d={fi:.3f}")
        if fo:
            vf.append(f"fade=t=out:st={dur - fo:.3f}:d={fo:.3f}")
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-vn"]

    if p["has_audio"] and not p["mute"]:
        # Normalisation et volume d'abord, pour que les fondus restent exacts
        af = []
        if p["normalize"]:
            af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if p["gain"]:
            af.append(f"volume={p['gain']:.1f}dB")
        if fi:
            af.append(f"afade=t=in:st=0:d={fi:.3f}")
        if fo:
            af.append(f"afade=t=out:st={dur - fo:.3f}:d={fo:.3f}")
        if af:
            cmd += ["-af", ",".join(af)]
        cmd += AUDIO_CODECS[fmt]
        if p["normalize"]:
            cmd += ["-ar", "48000"]  # loudnorm suréchantillonne à 192 kHz sinon
    else:
        cmd += ["-an"]

    if fmt in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    return cmd + [str(out)]


@app.post("/api/library/{item_id}/edit")
async def start_edit(item_id: str, payload: EditRequest):
    item = _item_or_404(item_id)
    src = DOWNLOAD_DIR / item_id / item["filename"]
    try:
        probe = await asyncio.get_running_loop().run_in_executor(None, _probe, src)
    except Exception:
        raise HTTPException(status_code=500, detail="Impossible de lire ce fichier (ffprobe).")

    def bad(msg: str):
        raise HTTPException(status_code=400, detail=msg)

    start, end = payload.start, payload.end
    if start < 0 or end <= start or (probe["duration"] and end > probe["duration"] + 0.5):
        bad("Début et fin invalides.")
    dur = end - start
    if dur < 0.1:
        bad("La sélection est trop courte.")
    if payload.fade_in < 0 or payload.fade_out < 0 or payload.fade_in + payload.fade_out > dur:
        bad("Les fondus sont plus longs que la sélection.")
    if not -20 <= payload.gain <= 20:
        bad("Le volume doit rester entre -20 et +20 dB.")

    src_ext = src.suffix.lstrip(".").lower()
    if payload.fast:
        if payload.fade_in or payload.fade_out or payload.gain or payload.normalize:
            bad("La coupe rapide ne permet ni fondus ni réglage du volume.")
        if payload.format and payload.format != src_ext:
            bad("La coupe rapide garde le format d'origine.")
        fmt = src_ext
    else:
        fmt = payload.format or src_ext
        allowed = {"mp3", "wav"} if probe["has_audio"] else set()
        if probe["has_video"]:
            allowed |= {"mp4", "mov"}
        if fmt not in allowed:
            bad("Ce format de sortie n'est pas possible pour ce fichier.")
        if fmt in ("mp3", "wav") and payload.mute:
            bad("Impossible de supprimer le son d'un fichier audio.")

    title = f"{item['title']} (édité)"
    data = {**payload.model_dump(), "format": fmt, "src": str(src),
            "filename": f"{src.stem[:150]} (édité).{fmt}", **probe}
    job = _new_job("edit", title, item.get("thumbnail"), data)
    job_dir = DOWNLOAD_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {"status": "queued", "kind": "edit", "parent": item_id, "title": title,
                          "created": job["created"]})
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _edit_sync(job: dict) -> None:
    p = job["_payload"]
    job_dir = DOWNLOAD_DIR / job["id"]
    out = job_dir / p["filename"]
    log_path = job_dir / ".ffmpeg.log"
    total = p["end"] - p["start"]
    job["status"] = "processing"

    _run_ffmpeg(job, _build_edit_cmd(p, Path(p["src"]), out), total, log_path, "Le montage a échoué")
    if not out.exists():
        raise RuntimeError("Le montage a échoué : aucun fichier produit.")

    job["filename"] = out.name
    parent = _read_meta(Path(p["src"]).parent)
    _write_meta(job_dir, {
        "status": "done",
        "kind": "edit",
        "parent": Path(p["src"]).parent.name,
        "title": job["title"],
        "thumbnail": job["thumbnail"],
        "duration": round(total, 2),
        "source": parent.get("source"),
        "created": job["created"],
    })


# ---------------------------------------------------------------------------
# Liste de sons : titres écrits ou lus sur des captures, cherchés puis rendus en zip
# ---------------------------------------------------------------------------

def _load_sons() -> list:
    try:
        data = json.loads(SONS_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_sons(sons: list) -> None:
    tmp = SONS_FILE.with_name(".liste-sons.tmp")
    tmp.write_text(json.dumps(sons, ensure_ascii=False), "utf-8")
    tmp.replace(SONS_FILE)


def _clean_query(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:200]


def _add_sons(queries: list) -> list:
    with SONS_LOCK:
        sons = _load_sons()
        known = {s["query"].casefold() for s in sons}
        for raw in queries:
            query = _clean_query(raw)
            if query and query.casefold() not in known:
                known.add(query.casefold())
                sons.append({"id": uuid.uuid4().hex, "query": query, "note": None})
        _save_sons(sons)
        return sons


@app.get("/api/sons")
async def list_sons():
    return _load_sons()


@app.post("/api/sons")
async def add_sons(payload: SonsAddRequest):
    return _add_sons(payload.queries)


@app.patch("/api/sons/{son_id}")
async def update_son(son_id: str, payload: SonUpdateRequest):
    query = _clean_query(payload.query)
    if not query:
        raise HTTPException(status_code=400, detail="Le titre ne peut pas être vide.")
    with SONS_LOCK:
        sons = _load_sons()
        for son in sons:
            if son["id"] == son_id:
                son.update(query=query, note=None, pick=None)
        _save_sons(sons)
        return sons


@app.put("/api/sons/{son_id}/pick")
async def pick_son(son_id: str, payload: SonPickRequest):
    """Vidéo YouTube choisie à la main pour ce titre : elle sera téléchargée telle quelle."""
    pick = {"id": payload.video_id, "title": _clean_query(payload.title) or payload.video_id}
    with SONS_LOCK:
        sons = _load_sons()
        for son in sons:
            if son["id"] == son_id:
                son.update(pick=pick, note=None)
        _save_sons(sons)
        return sons


@app.delete("/api/sons/{son_id}/pick")
async def unpick_son(son_id: str):
    with SONS_LOCK:
        sons = _load_sons()
        for son in sons:
            if son["id"] == son_id:
                son["pick"] = None
        _save_sons(sons)
        return sons


@app.get("/api/sons/search")
async def search_youtube(q: str):
    """Résultats YouTube pour la fenêtre de choix d'un son introuvable."""
    query = _clean_query(q)
    if not query:
        return []
    try:
        return await asyncio.get_running_loop().run_in_executor(None, _youtube_results, query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_humanize_error(exc))


@app.delete("/api/sons/{son_id}")
async def delete_son(son_id: str):
    with SONS_LOCK:
        sons = [s for s in _load_sons() if s["id"] != son_id]
        _save_sons(sons)
        return sons


@app.delete("/api/sons")
async def clear_sons():
    with SONS_LOCK:
        _save_sons([])
    return []


# Lignes d'interface des applis musicales (Spotify, Deezer, Apple Music, YouTube Music…)
OCR_NOISE = re.compile(
    r"^(lecture( aléatoire)?|aléatoire|shuffle|play|pause|playlist|album|single|ep|titres?|songs?|"
    r"morceaux|tracks?|télécharger|download(ed)?|accueil|home|rechercher|search|bibliothèque|"
    r"your library|library|premium|créer|create|ajouter|add|suivre|follow|abonné|partager|share|"
    r"radio|explicit|e|recommandés|recommended|voir tout|see all|modifier|edit|trier|sort|"
    r"à suivre|up next|en cours de lecture|now playing|paroles|lyrics|mix|spotify|deezer|"
    r"apple music|youtube music|soundcloud|tidal|.*\d+ ?(titres|songs|morceaux|likes?|j'aime|min)\b.*|"
    r"\d+ ?(h|min|s)( \d+ ?(min|s))*)$",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


# Tesseract perd souvent les accents : on compare aussi sans
OCR_NOISE_PLAIN = re.compile(_strip_accents(OCR_NOISE.pattern), re.IGNORECASE)


def _is_ocr_noise(text: str) -> bool:
    return bool(OCR_NOISE.match(text) or OCR_NOISE_PLAIN.match(_strip_accents(text)))


def _clean_ocr_line(text: str) -> Optional[str]:
    if _is_ocr_noise(text.strip()):
        return None
    text = re.sub(r"[|•·●‧◦»«©®™]+", " ", text)
    text = re.sub(r"^\s*(\d{1,3}[.)]?|[^\w(]+)\s+", "", text)  # numéro de piste, puce
    text = re.sub(r"\s+\d{1,2}[:.]\d{2}(:\d{2})?\s*$", "", text)  # durée en fin de ligne
    text = re.sub(r"^E\s+(?=\S)", "", text)  # badge « explicite » devant l'artiste
    text = re.sub(r"\s+(\.{3}|…|:)\s*$", "", text)
    text = _clean_query(text.strip(" -–—_.,;:'\"*~=+<>/\\"))
    letters = sum(c.isalpha() for c in text)
    if letters < 2 or letters < len(text) * 0.45 or _is_ocr_noise(text):
        return None
    if re.fullmatch(r"[\d\s:%.,]+.*", text) and letters < 4:  # heure, batterie…
        return None
    return text


def _ocr_lines(image: Path) -> list:
    """Lit une capture avec Tesseract et regroupe titre + artiste quand ils sont empilés."""
    with tempfile.TemporaryDirectory() as tmp:
        # Agrandie et en niveaux de gris : Tesseract lit mieux les petits textes d'écran
        prepared = Path(tmp) / "screen.png"
        subprocess.run(
            [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(image),
             "-vf", "scale=iw*2:ih*2:flags=lanczos,format=gray", "-frames:v", "1", str(prepared)],
            capture_output=True, timeout=60, check=True,
        )
        out = subprocess.run(
            [TESSERACT, str(prepared), "stdout", "-l", "fra+eng", "--psm", "11", "tsv"],
            capture_output=True, text=True, timeout=120,
        )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "Tesseract a échoué.")

    # Mots → lignes (block, paragraphe, ligne), avec leur position
    lines: Dict[tuple, dict] = {}
    for row in out.stdout.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
            continue
        if float(cols[10]) < 30:
            continue
        key = (int(cols[2]), int(cols[3]), int(cols[4]))
        left, top, width, height = (int(c) for c in cols[6:10])
        line = lines.setdefault(key, {"words": [], "left": left, "top": top, "right": 0, "bottom": 0})
        line["words"].append(cols[11])
        line["left"] = min(line["left"], left)
        line["top"] = min(line["top"], top)
        line["right"] = max(line["right"], left + width)
        line["bottom"] = max(line["bottom"], top + height)

    # Le mode « texte épars » coupe parfois une ligne en morceaux : on recolle ceux qui se suivent
    merged: list = []
    for line in sorted(lines.values(), key=lambda l: (l["top"], l["left"])):
        prev = merged[-1] if merged else None
        h = line["bottom"] - line["top"]
        if prev and abs(prev["top"] - line["top"]) < h * 0.5 and 0 <= line["left"] - prev["right"] < h * 2:
            prev["words"] += line["words"]
            prev["right"] = max(prev["right"], line["right"])
            prev["bottom"] = max(prev["bottom"], line["bottom"])
        else:
            merged.append(dict(line))

    entries = []
    for line in merged:
        text = _clean_ocr_line(" ".join(line["words"]))
        if text:
            entries.append({**line, "text": text, "height": line["bottom"] - line["top"]})

    # Titre puis artiste juste en dessous, alignés à gauche : on les réunit en « Titre - Artiste »
    results, i = [], 0
    while i < len(entries):
        cur = entries[i]
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        if nxt:
            h = min(cur["height"], nxt["height"])
            gap = nxt["top"] - cur["bottom"]
            if -h * 0.2 <= gap < h * 1.25 and abs(nxt["left"] - cur["left"]) < h * 1.5:
                results.append(f"{cur['text']} - {nxt['text']}")
                i += 2
                continue
        results.append(cur["text"])
        i += 1
    return results


@app.post("/api/sons/ocr")
async def sons_from_screen(request: Request):
    """Reçoit une capture (corps brut de la requête), y lit les titres et les ajoute à la liste."""
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Image vide.")
    if len(data) > MAX_SCREEN_BYTES:
        raise HTTPException(status_code=413, detail="Capture trop lourde (20 Mo maximum).")
    with tempfile.NamedTemporaryFile(suffix=".img") as f:
        f.write(data)
        f.flush()
        try:
            found = await asyncio.get_running_loop().run_in_executor(None, _ocr_lines, Path(f.name))
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="Tesseract (lecture des captures) est introuvable sur le serveur.")
        except Exception:
            raise HTTPException(status_code=400, detail="Impossible de lire cette image.")
    before = {s["id"] for s in _load_sons()}
    sons = _add_sons(found)
    added = [s for s in sons if s["id"] not in before]
    return {"sons": sons, "added": len(added), "read": len(found)}


@app.post("/api/sons/fetch")
async def fetch_sons(payload: SonsFetchRequest):
    if any(j["kind"] == "sons" and j["status"] in ACTIVE_STATUSES for j in JOBS.values()):
        raise HTTPException(status_code=409, detail="Une recherche de la liste est déjà en cours.")
    sons = _load_sons()
    if not sons:
        raise HTTPException(status_code=400, detail="La liste est vide.")
    n = len(sons)
    title = f"Liste de sons · {n} titre{'s' if n > 1 else ''}"
    data = {"sons": [{"id": s["id"], "query": s["query"], "video_id": (s.get("pick") or {}).get("id")}
                     for s in sons], **payload.model_dump()}
    job = _new_job("sons", title, None, data)
    job.update(step=None, found=0, missing=0)
    job_dir = DOWNLOAD_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {"status": "queued", "kind": "sons", "title": title, "created": job["created"]})
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _youtube_results(query: str, count: int = 12) -> list:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False) or {}
    results = []
    for e in info.get("entries") or []:
        video_id = (e or {}).get("id")
        if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            continue  # chaînes ou playlists
        results.append({
            "id": video_id,
            "title": e.get("title") or video_id,
            "channel": e.get("channel") or e.get("uploader"),
            "duration": e.get("duration"),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        })
    return results


def _search_son(query: str) -> list:
    """Quelques résultats YouTube pour la recherche, en écartant les mix et albums entiers."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch5:{query}", download=False) or {}
    entries = [e for e in info.get("entries") or [] if e and (e.get("url") or e.get("id"))]
    ok = [e for e in entries if not e.get("duration") or e["duration"] <= MAX_SON_DURATION]
    return [e.get("url") or f"https://www.youtube.com/watch?v={e['id']}" for e in ok[:2]]


def _sons_sync(job: dict) -> None:
    p = job["_payload"]
    job_dir = DOWNLOAD_DIR / job["id"]
    work = job_dir / ".pistes"
    work.mkdir(exist_ok=True)
    sons = p["sons"]
    total = len(sons)
    found: Dict[str, Path] = {}
    missing: Dict[str, str] = {}

    for index, son in enumerate(sons):
        if job["_cancel"]:
            raise JobCancelled()
        job.update(status="downloading", step=f"{index + 1}/{total} · {son['query']}", speed=None, eta=None,
                   progress=round(index / total * 100, 1))

        def progress_hook(d: dict, index=index) -> None:
            if job["_cancel"]:
                raise JobCancelled()
            if d["status"] == "downloading":
                done_bytes = d.get("downloaded_bytes") or 0
                size = d.get("total_bytes") or d.get("total_bytes_estimate")
                fraction = min(1.0, done_bytes / size) if size else 0
                job.update(progress=round((index + fraction) / total * 100, 1),
                           speed=d.get("speed"), eta=None)

        target = work / f"{index:03d}"
        target.mkdir(exist_ok=True)
        opts = {
            "outtmpl": str(target / "%(title).150s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": p["container"],
                "preferredquality": p["audio_quality"] or "0",
            }],
        }
        if p["container"] != "wav":
            opts["writethumbnail"] = True
            opts["postprocessors"].append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        _tag_options(opts, opts["postprocessors"], p["container"])
        reason = "aucun résultat sur YouTube"
        try:
            urls = ([f"https://www.youtube.com/watch?v={son['video_id']}"] if son.get("video_id")
                    else _search_son(son["query"]))
            for url in urls:
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.add_post_processor(_FileTags(ydl, music=True), when="pre_process")
                        if opts.get("writethumbnail"):
                            ydl.add_post_processor(_CoverArt(ydl), when="post_process")
                        ydl.extract_info(url, download=True)
                    media = _media_file(target)
                    if media:
                        found[son["id"]] = media
                        break
                except Exception as exc:
                    if job["_cancel"]:
                        raise JobCancelled()
                    reason = _humanize_error(exc)
                    for leftover in target.iterdir():
                        leftover.unlink(missing_ok=True)
        except JobCancelled:
            raise
        except Exception as exc:
            if job["_cancel"]:
                raise JobCancelled()
            reason = _humanize_error(exc)
        if son["id"] not in found:
            missing[son["id"]] = reason
        job.update(found=len(found), missing=len(missing))

    if job["_cancel"]:
        raise JobCancelled()

    # Tous les sons restent dans la liste ; ceux qui manquent y gagnent la raison
    with SONS_LOCK:
        current = _load_sons()
        for son in current:
            if son["id"] in missing:
                son["note"] = missing[son["id"]]
            elif son["id"] in found:
                son["note"] = None
        _save_sons(current)

    if not found:
        raise RuntimeError("Aucun son trouvé.")

    job.update(status="converting", step=None, speed=None)
    stamp = time.strftime("%Y-%m-%d %Hh%M", time.localtime(job["created"]))
    zip_path = job_dir / f"Liste de sons {stamp}.zip"
    used = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:  # MP3 déjà compressé
        for media in found.values():
            name, n = media.name, 2
            while name.casefold() in used:
                name = f"{media.stem} ({n}){media.suffix}"
                n += 1
            used.add(name.casefold())
            zf.write(media, name)
    shutil.rmtree(work, ignore_errors=True)

    count = len(found)
    job["title"] = f"Liste de sons · {count} titre{'s' if count > 1 else ''}"
    job["filename"] = zip_path.name
    job["step"] = None
    _write_meta(job_dir, {
        "status": "done",
        "kind": "sons",
        "title": job["title"],
        "count": count,
        "created": job["created"],
    })
