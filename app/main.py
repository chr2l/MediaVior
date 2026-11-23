import asyncio
import hashlib
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
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import yt_dlp

if sys.platform.startswith("win"):
    class _HiddenPopen(subprocess.Popen):
        """Windows : aucune commande lancée par l'appli (ffmpeg, streamrip, Votify…) n'ouvre de
        fenêtre noire, sauf si l'appel demande lui-même d'autres options (creationflags)."""

        def __init__(self, *args, **kwargs):
            if not kwargs.get("creationflags"):
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _HiddenPopen
from yt_dlp.postprocessor import EmbedThumbnailPP, PostProcessor

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.environ.get("LECOFFRE_DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Les médias finis sont rangés directement dans DOWNLOAD_DIR. Leurs fiches (titre, pochette…)
# et les fichiers en cours de téléchargement vont dans ce sous-dossier caché.
ITEMS_DIR = DOWNLOAD_DIR / ".mediavior"
# Dossiers à part pour les sons et pour les vidéos (version PC, réglages). Vide = dossier principal.
AUDIO_DIR: "Optional[Path]" = Path(os.environ["LECOFFRE_AUDIO_DIR"]) if os.environ.get("LECOFFRE_AUDIO_DIR") else None
VIDEO_DIR: "Optional[Path]" = Path(os.environ["LECOFFRE_VIDEO_DIR"]) if os.environ.get("LECOFFRE_VIDEO_DIR") else None
for _d in (AUDIO_DIR, VIDEO_DIR):
    if _d:
        try:
            _d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
# Historique des téléchargements pour les stats du coffre : il garde tout ce qui a été téléchargé,
# même si les fichiers sont ensuite déplacés ailleurs. Hors du dossier des médias (version PC :
# ~/.mediavior), pour survivre aussi à un changement de dossier.
STATE_DIR = Path(os.environ.get("MEDIAVIOR_STATE_DIR") or ITEMS_DIR)
HISTORY_FILE = STATE_DIR / "historique.json"
HISTORY_LOCK = threading.Lock()


def _prepare_items_dir(d: Path) -> None:
    d.mkdir(exist_ok=True)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(d), 0x2)  # dossier caché
        except Exception:
            pass


_prepare_items_dir(ITEMS_DIR)
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

APP_NAME = "MediaVior"
GITHUB_URL = "https://github.com/chr2l/MediaVior"
# Mode local : l'appli tourne sur le PC de la personne (lancée par mediavior.py),
# pas sur un serveur. Ajoute « Ouvrir le dossier » et « Quitter », et protège l'API
# contre les autres sites ouverts dans le navigateur.
LOCAL_MODE = os.environ.get("MEDIAVIOR_LOCAL") == "1"
QUIT_HOOK = None  # fourni par mediavior.py pour arrêter le serveur proprement
# Appli prête à installer (.exe, .dmg, AppImage) : nouvelle version publiée et installation
APP_UPDATE: Optional[dict] = None
APP_UPDATE_HOOK = None
APP_UPDATE_CHECK = None  # relance la vérification sur GitHub (bouton des Réglages)
PAGE_SEEN = False  # la page a demandé l'état de la mise à jour (après une relance : pas de 2e fenêtre)
# Version PC : numéro de version de l'appli installée, réglages gardés par mediavior.py
APP_VERSION: Optional[str] = None
FOLDER_HOOK = None  # retient le nouveau dossier des médias (config de mediavior.py)
KIND_FOLDER_HOOK = None  # retient le dossier à part des sons / des vidéos (kind, chemin ou None)
WINDOW_HOOK = None  # fenêtre installée dans Edge/Chrome : WINDOW_HOOK() → état, WINDOW_HOOK(url) ouvre un onglet
AUTOSTART_HOOK = None  # lancement au démarrage du PC : AUTOSTART_HOOK() lit, AUTOSTART_HOOK(True/False) règle

# Change à chaque démarrage : force le navigateur à recharger CSS/JS après une mise à jour
ASSET_VERSION = str(int(time.time()))
# Date de la dernière mise à jour de l'appli : le fichier de code le plus récent de l'image
UPDATED_AT = int(max(
    (p.stat().st_mtime for p in BASE_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts),
    default=time.time(),
))

META_FILE = "meta.json"
ITEM_ID = re.compile(r"^[0-9a-f]{32}$")
AUDIO_EXTS = {".mp3", ".wav", ".aiff", ".aif", ".m4a", ".opus", ".ogg", ".flac", ".aac"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_CONTAINERS = {"original", "mp4", "mov"}
AUDIO_CONTAINERS = {"original", "mp3", "flac", "wav", "aiff"}
# Formats où yt-dlp sait intégrer une pochette (le WebM n'en accepte pas)
COVER_EXTS = {"mp3", "m4a", "opus", "ogg", "flac", "mp4", "m4v", "mkv", "mka"}
YTDLP_CHECK_EVERY = 12 * 3600  # vérification d'une nouvelle version de yt-dlp
IGNORED_SUFFIXES = {".part", ".ytdl", ".temp", ".tmp"}
ACTIVE_STATUSES = {"queued", "downloading", "converting", "processing"}
TESSERACT = os.environ.get("TESSERACT_BIN", "tesseract")
SONS_FILE = ITEMS_DIR / "liste-sons.json"
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
    tasks = [asyncio.create_task(_worker()), asyncio.create_task(_ytdlp_updater())]
    if LOCAL_MODE:
        tasks += jumelage.setup(sys.modules[__name__])  # liaison avec le téléphone
        if EXTENSION_TARGET.is_dir():  # extension déjà ajoutée : on la garde à jour avec l'appli
            try:
                _copy_extension()
            except OSError:
                pass
    yield
    for task in tasks:
        task.cancel()


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


# Aperçu (page web publique) : les visiteurs voient l'interface, mais rien ne se télécharge sur ce
# serveur et rien du coffre n'est montré. Seul l'administrateur garde l'outil complet : la porte
# d'elie.place envoie « X-Elie-Role: admin » quand il est connecté, et efface cet en-tête s'il vient
# du navigateur. À n'activer (MEDIAVIOR_APERCU=1) que derrière cette porte.
APERCU = not LOCAL_MODE and os.environ.get("MEDIAVIOR_APERCU") == "1"
APERCU_MSG = "Ceci est un aperçu : télécharge MediaVior pour l'utiliser sur ton ordinateur."


def is_apercu(request: Request) -> bool:
    return APERCU and request.headers.get("x-elie-role") != "admin"


if APERCU:
    @app.middleware("http")
    async def _apercu_guard(request: Request, call_next):
        path = request.url.path
        if is_apercu(request):
            if path in ("/api/ping", "/api/prompt"):
                return await call_next(request)
            if request.method == "GET" and path in ("/api/library", "/api/jobs", "/api/sons"):
                return JSONResponse([])  # coffre vide pour les visiteurs
            if request.method == "GET" and path == "/api/stats":
                return JSONResponse({"total": 0})
            if request.method == "GET" and path == "/api/preferences":
                return JSONResponse({"video": None, "audio": None, "quality": None})
            if path.startswith("/api/"):
                return JSONResponse({"detail": APERCU_MSG, "apercu": True}, status_code=403)
            if path.startswith("/edit/"):
                return RedirectResponse("/", status_code=303)
        return await call_next(request)


if LOCAL_MODE:
    import jumelage  # app/jumelage.py : téléphone jumelé (QR code), version PC seulement
    app.include_router(jumelage.router)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["local"] = LOCAL_MODE  # version PC : toutes les pages le savent (liens.js)


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
    container: Literal["original", "mp4", "mov", "mp3", "flac", "wav", "aiff"]
    audio_quality: Optional[str] = None  # MP3 uniquement : "320", "192", "128" ("0" = VBR V0)
    title: Optional[str] = None
    thumbnail: Optional[str] = None


class LinksRequest(BaseModel):
    """Plusieurs liens, un même format : tout finit dans un seul zip."""
    urls: list[str] = Field(min_length=1, max_length=100)
    mode: Literal["video", "audio"]
    quality: Optional[str] = None
    container: Literal["original", "mp4", "mov", "mp3", "flac", "wav", "aiff"]
    audio_quality: Optional[str] = None


class SonsAddRequest(BaseModel):
    queries: list[str]


class SonUpdateRequest(BaseModel):
    query: str


class SonPickRequest(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = ""


class SonsFetchRequest(BaseModel):
    container: Literal["mp3", "wav", "aiff"] = "mp3"
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

def _app_page(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "v": ASSET_VERSION, "ytdlp": yt_dlp.version.__version__, "updated": UPDATED_AT,
        "version": APP_VERSION, "local": LOCAL_MODE, "github": GITHUB_URL, "folder": str(DOWNLOAD_DIR),
        "apercu": is_apercu(request),
    })


def _vitrine_page(request: Request):
    return templates.TemplateResponse(request, "vitrine.html", {
        "v": ASSET_VERSION, "github": GITHUB_URL, "apercu_url": "/apercu" if APERCU else None,
        # Page du téléphone (relais), même adresse que dans jumelage.py
        "telephone_url": os.environ.get("MEDIAVIOR_RELAIS", "https://mediavior-tel.elie.place").rstrip("/"),
    })


@app.get("/")
async def index(request: Request):
    # Site public : les visiteurs arrivent sur la vitrine ; l'appli reste visible sur /apercu
    if is_apercu(request):
        return _vitrine_page(request)
    return _app_page(request)


@app.get("/apercu")
async def apercu(request: Request):
    if not APERCU:
        return RedirectResponse("/", status_code=303)
    return _app_page(request)


@app.get("/vitrine")
async def vitrine(request: Request):
    return _vitrine_page(request)


@app.get("/legal")
async def legal(request: Request):
    return templates.TemplateResponse(request, "legal.html", {"v": ASSET_VERSION, "github": GITHUB_URL})


# ---------------------------------------------------------------------------
# Version locale (PC) : prompt d'installation, dossier, arrêt
# ---------------------------------------------------------------------------

def _prompt_file(lang: str = "fr") -> Optional[Path]:
    # app/ en local (le dépôt entier est là), /app dans l'image Docker. PROMPT.en.md = version anglaise
    names = ["PROMPT.en.md", "PROMPT.md"] if lang == "en" else ["PROMPT.md"]
    for p in (folder / name for name in names for folder in (BASE_DIR.parent, BASE_DIR)):
        if p.is_file():
            return p
    return None


@app.get("/api/ping")
async def ping():
    return {"app": "mediavior", "local": LOCAL_MODE}


@app.get("/api/prompt", response_class=PlainTextResponse)
async def install_prompt(lang: str = "fr"):
    """Le prompt à coller dans une IA pour installer MediaVior sur son propre PC."""
    p = _prompt_file(lang)
    if not p:
        raise HTTPException(status_code=404, detail="Prompt introuvable.")
    return p.read_text(encoding="utf-8")


def _local_only() -> None:
    if not LOCAL_MODE:
        raise HTTPException(status_code=404, detail="Disponible seulement dans la version PC.")


def _show_in_explorer(target: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@app.post("/api/local/open-folder")
async def open_folder():
    _local_only()
    _show_in_explorer(DOWNLOAD_DIR)
    return {"ok": True}


class OpenLinkRequest(BaseModel):
    url: str


@app.post("/api/local/open-link")
async def open_link(req: OpenLinkRequest):
    """Ouvre un lien dans le navigateur par défaut de l'ordinateur.
    La fenêtre de l'appli tourne dans Edge/Chrome : sans ça, ses liens s'ouvriraient dans ce navigateur-là."""
    _local_only()
    if urlparse(req.url).scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Lien non pris en charge.")
    import webbrowser
    await asyncio.get_running_loop().run_in_executor(None, webbrowser.open, req.url)
    return {"ok": True}


@app.post("/api/local/fenetre")
async def window_install_tab():
    """Ouvre MediaVior dans un onglet ordinaire d'Edge/Chrome : c'est là que le navigateur
    propose « Installer », pour avoir la fenêtre aux couleurs de l'appli."""
    _local_only()
    if not WINDOW_HOOK:
        raise HTTPException(status_code=400, detail="Impossible ici.")
    ok = await asyncio.get_running_loop().run_in_executor(
        None, WINDOW_HOOK, "/?fenetre=1")
    if not ok:
        raise HTTPException(status_code=400, detail="Edge ou Chrome est nécessaire.")
    return {"ok": True}


# Réglages de la version PC : dossier des médias, lancement au démarrage
class SettingsRequest(BaseModel):
    folder: Optional[str] = None
    move: bool = True  # déplacer aussi les médias déjà rangés vers le nouveau dossier
    autostart: Optional[bool] = None
    # Dossier à part pour les sons / pour les vidéos ; "" = revenir au dossier principal
    audio_folder: Optional[str] = None
    video_folder: Optional[str] = None
    # Navigateur dont on utilise la connexion ("" = aucun)
    login_browser: Optional[str] = None
    # streamrip (sans perte Qobuz / Deezer) : "" = effacer ; None = ne pas toucher
    qobuz_email: Optional[str] = Field(None, max_length=200)
    qobuz_password: Optional[str] = Field(None, max_length=200)
    deezer_arl: Optional[str] = Field(None, max_length=500)
    spotify_sp_dc: Optional[str] = Field(None, max_length=1000)
    # Accord donné dans la fenêtre d'avertissement : obligatoire pour activer une connexion ou un compte
    accept_risks: bool = False


def _autostart_state() -> Optional[bool]:
    """None : réglage impossible ici (version serveur, Pinokio…)."""
    if not AUTOSTART_HOOK:
        return None
    try:
        return bool(AUTOSTART_HOOK())
    except Exception:
        return None


def _window_state() -> Optional[dict]:
    """None : pas de navigateur Edge/Chrome géré par le lanceur (Pinokio, serveur…)."""
    if not WINDOW_HOOK:
        return None
    try:
        return WINDOW_HOOK()
    except Exception:
        return None


def _settings() -> dict:
    return {"folder": str(DOWNLOAD_DIR), "autostart": _autostart_state(), "version": APP_VERSION,
            "window": _window_state(),
            "audio_folder": str(AUDIO_DIR) if AUDIO_DIR else None,
            "video_folder": str(VIDEO_DIR) if VIDEO_DIR else None,
            "login_browser": _login_browser(), "login_error": LOGIN_STATE["error"],
            "streamrip": _streamrip_state(),
            "count": sum(1 for d in ITEMS_DIR.iterdir() if d.is_dir() and ITEM_ID.match(d.name))}


def _change_folder(new: Path, move: bool) -> None:
    """Change le dossier des médias pendant que l'appli tourne. Avec move, les médias déjà rangés
    (et leurs fiches) suivent ; sinon ils restent dans l'ancien dossier, hors de l'appli."""
    global DOWNLOAD_DIR, ITEMS_DIR, SONS_FILE
    new_items = new / ".mediavior"
    _prepare_items_dir(new_items)
    if move:
        for d in list(ITEMS_DIR.iterdir()):
            if not (d.is_dir() and ITEM_ID.match(d.name)) or (new_items / d.name).exists():
                continue
            meta = _read_meta(d)
            media = _media_file(d, meta)
            if media and meta.get("file") and not meta.get("dir"):  # sons / vidéos à part : restent
                target = _free_name(media.name, new)
                shutil.move(str(media), str(target))
                meta["file"] = target.name
                _write_meta(d, meta)
            shutil.move(str(d), str(new_items / d.name))
        new_sons = new_items / SONS_FILE.name
        if SONS_FILE.is_file() and not new_sons.exists():
            shutil.move(str(SONS_FILE), str(new_sons))
        try:
            ITEMS_DIR.rmdir()  # ancien dossier caché, vide : on ne laisse rien traîner
        except OSError:
            pass
    DOWNLOAD_DIR, ITEMS_DIR, SONS_FILE = new, new_items, new_items / SONS_FILE.name


@app.get("/api/local/settings")
async def get_settings():
    _local_only()
    return _settings()


def _writable_folder(raw: str) -> Path:
    """Chemin donné par la personne → dossier existant où l'appli peut écrire, sinon erreur claire."""
    new = Path(raw.strip()).expanduser()
    if not new.is_absolute():
        raise HTTPException(status_code=400, detail="Donne le chemin complet du dossier.")
    try:
        new = new.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Ce dossier est introuvable.")
    if new == ITEMS_DIR.resolve() or ITEMS_DIR.resolve() in new.parents:
        raise HTTPException(status_code=400, detail="Choisis un autre dossier.")
    try:
        new.mkdir(parents=True, exist_ok=True)
        probe = new / ".mediavior-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        raise HTTPException(status_code=400, detail="Impossible d'écrire dans ce dossier.")
    return new


@app.post("/api/local/settings")
async def save_settings(payload: SettingsRequest):
    global AUDIO_DIR, VIDEO_DIR
    _local_only()
    if payload.autostart is not None:
        if not AUTOSTART_HOOK:
            raise HTTPException(status_code=400, detail="Le lancement au démarrage n'est pas possible ici.")
        try:
            AUTOSTART_HOOK(payload.autostart)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Réglage impossible : {exc}")
    if payload.login_browser is not None:
        browser = payload.login_browser or None
        if browser and browser not in LOGIN_BROWSERS:
            raise HTTPException(status_code=400, detail="Navigateur inconnu.")
        if browser and browser != _login_browser() and not payload.accept_risks:
            raise HTTPException(status_code=400, detail="Accepte d'abord l'avertissement.")
        try:
            _set_login_browser(browser)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Réglage impossible : {exc}")
    fields = ("qobuz_email", "qobuz_password", "deezer_arl", "spotify_sp_dc")
    if any(getattr(payload, f) is not None for f in fields):
        if not _streamrip_state():
            raise HTTPException(status_code=400, detail="Ni streamrip ni Votify n'est installé ici.")
        if any((getattr(payload, f) or "").strip() for f in fields) and not payload.accept_risks:
            raise HTTPException(status_code=400, detail="Accepte d'abord l'avertissement.")
        creds = _streamrip_creds()
        if payload.qobuz_email is not None:
            email = payload.qobuz_email.strip()
            creds["qobuz_email"] = email
            if not email:
                creds.pop("qobuz_password", None)
        if payload.qobuz_password:  # streamrip veut l'empreinte md5 du mot de passe Qobuz
            creds["qobuz_password"] = hashlib.md5(payload.qobuz_password.encode("utf-8")).hexdigest()
        for f in ("deezer_arl", "spotify_sp_dc"):
            if getattr(payload, f) is not None:
                creds[f] = getattr(payload, f).strip()
        creds = {k: v for k, v in creds.items() if v}
        try:
            _streamrip_save(creds)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Réglage impossible : {exc}")
    for kind in ("audio", "video"):
        raw = getattr(payload, f"{kind}_folder")
        if raw is None:
            continue
        target = _writable_folder(raw) if raw.strip() else None
        if target and target == DOWNLOAD_DIR.resolve():
            target = None  # même dossier que le principal : rien de spécial
        if kind == "audio":
            AUDIO_DIR = target
        else:
            VIDEO_DIR = target
        if KIND_FOLDER_HOOK:
            KIND_FOLDER_HOOK(kind, str(target) if target else None)
    if payload.folder:
        new = Path(payload.folder).expanduser()
        if not new.is_absolute():
            raise HTTPException(status_code=400, detail="Donne le chemin complet du dossier.")
        try:
            new = new.resolve()
        except OSError:
            raise HTTPException(status_code=400, detail="Ce dossier est introuvable.")
        if new != DOWNLOAD_DIR.resolve():
            if new == ITEMS_DIR.resolve() or ITEMS_DIR.resolve() in new.parents:
                raise HTTPException(status_code=400, detail="Choisis un autre dossier.")
            if any(j["status"] in ACTIVE_STATUSES for j in JOBS.values()):
                raise HTTPException(status_code=409, detail="Attends la fin des téléchargements en cours.")
            try:
                new.mkdir(parents=True, exist_ok=True)
                probe = new / ".mediavior-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError:
                raise HTTPException(status_code=400, detail="Impossible d'écrire dans ce dossier.")
            try:
                await asyncio.get_running_loop().run_in_executor(None, _change_folder, new, payload.move)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Déplacement interrompu : {exc}")
            if FOLDER_HOOK:
                FOLDER_HOOK(str(new))
    return _settings()


def _app_window_win() -> int:
    """Windows : trouve la fenêtre MediaVior (celle où l'on vient de cliquer), 0 sinon."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    def title(hwnd) -> str:
        size = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(size + 1)
        user32.GetWindowTextW(hwnd, buf, size + 1)
        return buf.value

    front = user32.GetForegroundWindow()
    if front and "MediaVior" in title(front):
        return front
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and "MediaVior" in title(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(proc(each), 0)
    return found[0] if found else 0


def _x11_active_window() -> Optional[str]:
    """Linux (X11) : numéro de la fenêtre au premier plan, pour y rattacher le sélecteur."""
    if not shutil.which("xdotool") or not os.environ.get("DISPLAY"):
        return None
    try:
        out = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    wid = out.stdout.strip()
    return wid if wid.isdigit() else None


def _pick_folder_sync(start: str, title: str) -> Optional[str]:
    """Ouvre la fenêtre « Choisir un dossier » du système, au-dessus de la fenêtre MediaVior
    et rattachée à elle (modale). None si annulé ou impossible."""
    owner = 0
    flags = 0
    if sys.platform.startswith("win"):
        try:
            owner = _app_window_win()
        except Exception:  # noqa: BLE001 - sans fenêtre trouvée, on garde l'ancien comportement
            owner = 0
        start_ps = start.replace("'", "''")
        title_ps = title.replace("'", "''")
        # La fenêtre MediaVior devient « propriétaire » du sélecteur : Windows le garde
        # au-dessus d'elle et la bloque tant qu'il est ouvert, comme une vraie fenêtre de l'appli.
        ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
              "Add-Type -AssemblyName System.Windows.Forms; "
              "Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition "
              "'public class MvOwner : System.Windows.Forms.IWin32Window { "
              "public MvOwner(System.IntPtr h) { Handle = h; } "
              "public System.IntPtr Handle { get; private set; } }'; "
              "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
              f"$d.Description = '{title_ps}'; "
              f"$d.SelectedPath = '{start_ps}'; $d.ShowNewFolderButton = $true; "
              f"if ({int(owner)} -ne 0) {{ $o = New-Object MvOwner ([IntPtr]{int(owner)}) }} "
              "else { $o = New-Object System.Windows.Forms.Form -Property @{TopMost = $true} }; "
              "if ($d.ShowDialog($o) -eq 'OK') { $d.SelectedPath }")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", ps]
        flags = 0x08000000  # CREATE_NO_WINDOW : pas de fenêtre noire
    elif sys.platform == "darwin":
        # « activate » passe le sélecteur au premier plan, devant la fenêtre MediaVior.
        script = ("on run argv\n"
                  "activate\n"
                  "try\n"
                  "set here to (POSIX file (item 2 of argv)) as alias\n"
                  "return POSIX path of (choose folder with prompt (item 1 of argv) default location here)\n"
                  "on error number n\n"
                  "if n is -128 then return \"\"\n"
                  "end try\n"
                  "return POSIX path of (choose folder with prompt (item 1 of argv))\n"
                  "end run")
        cmd = ["osascript", "-e", script, title, start]
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--modal", f"--title={title}",
               f"--filename={start}/"]
        wid = _x11_active_window()
        if wid:
            cmd.append(f"--attach={wid}")
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", start, "--title", title]
        wid = _x11_active_window()
        if wid:
            cmd += ["--attach", wid]
    else:
        raise FileNotFoundError("aucune fenêtre de choix")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=600,
                             creationflags=flags)
    finally:
        if owner:  # sécurité : la fenêtre MediaVior ne doit jamais rester bloquée
            try:
                import ctypes
                ctypes.windll.user32.EnableWindow(owner, True)
                ctypes.windll.user32.SetForegroundWindow(owner)
            except Exception:  # noqa: BLE001
                pass
    path = out.stdout.strip()
    return path or None


class PickFolder(BaseModel):
    kind: Optional[str] = None  # "audio" / "video" : part du dossier déjà choisi pour ce type
    title: Optional[str] = None  # titre de la fenêtre, dans la langue de l'interface


_PICKING = threading.Lock()  # une seule fenêtre de choix à la fois


@app.post("/api/local/pick-folder")
async def pick_folder(payload: Optional[PickFolder] = None):
    _local_only()
    payload = payload or PickFolder()
    current = {"audio": AUDIO_DIR, "video": VIDEO_DIR}.get(payload.kind or "")
    start = str(current or DOWNLOAD_DIR)
    title = (payload.title or "Dossier des médias MediaVior").strip()[:120] or "MediaVior"
    if not _PICKING.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Une fenêtre de choix est déjà ouverte.")
    try:
        path = await asyncio.get_running_loop().run_in_executor(None, _pick_folder_sync, start, title)
    except (OSError, subprocess.SubprocessError):
        return {"path": None, "manual": True}  # pas de fenêtre de choix : on demande le chemin
    finally:
        _PICKING.release()
    return {"path": path}


# Extension de navigateur (dossier extension/), ajoutée sans passer par le Chrome Web Store :
# l'appli la copie dans un dossier facile à retrouver, que Chrome/Brave/Edge chargent en « mode
# développeur ». Ce dossier est recopié à chaque lancement : l'extension suit les mises à jour.
# Dans le dépôt elle est à côté de app/, dans l'appli installée à côté de main.py.
EXTENSION_SOURCE = next((p for p in (BASE_DIR.parent / "extension", BASE_DIR / "extension")
                         if (p / "manifest.json").is_file()), None)
_DOCUMENTS = Path.home() / "Documents"
EXTENSION_TARGET = (_DOCUMENTS if _DOCUMENTS.is_dir() else Path.home()) / "MediaVior extension"


def _copy_extension() -> None:
    if not EXTENSION_SOURCE:
        raise HTTPException(status_code=404, detail="Extension introuvable dans cette version.")
    shutil.copytree(EXTENSION_SOURCE, EXTENSION_TARGET, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.zip", ".*"))


@app.get("/api/local/extension")
async def extension_info():
    _local_only()
    return {"folder": str(EXTENSION_TARGET), "ready": EXTENSION_TARGET.is_dir(),
            "available": bool(EXTENSION_SOURCE)}


@app.post("/api/local/extension")
async def extension_prepare():
    """Copie l'extension dans Documents/MediaVior extension, puis ouvre ce dossier."""
    _local_only()
    try:
        _copy_extension()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Copie impossible : {exc}")
    try:
        _show_in_explorer(EXTENSION_TARGET)
    except OSError:
        pass  # pas d'explorateur de fichiers : le chemin reste affiché dans la fenêtre
    return {"folder": str(EXTENSION_TARGET)}


@app.get("/api/local/maj")
async def app_update_info():
    """Nouvelle version de l'appli prête à installer, s'il y en a une, version installée
    (« current ») et avancement de l'installation en cours (« install »)."""
    global PAGE_SEEN
    _local_only()
    PAGE_SEEN = True
    state = APP_UPDATE or {}
    return {**(state.get("release") or {}), "current": APP_VERSION, "install": state.get("install")}


@app.post("/api/local/maj/verifier")
async def app_update_check():
    """Bouton « Rechercher une mise à jour » : redemande à GitHub la dernière version."""
    _local_only()
    if not APP_UPDATE_CHECK:
        raise HTTPException(status_code=404, detail="Recherche de mise à jour indisponible ici.")
    try:
        await asyncio.get_running_loop().run_in_executor(None, APP_UPDATE_CHECK)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vérification impossible : {exc}")
    return {"version": APP_VERSION, "release": (APP_UPDATE or {}).get("release") or {}}


@app.post("/api/local/maj")
async def app_update_install():
    _local_only()
    if not APP_UPDATE_HOOK or not (APP_UPDATE or {}).get("release"):
        raise HTTPException(status_code=404, detail="Pas de mise à jour disponible.")
    try:
        await asyncio.get_running_loop().run_in_executor(None, APP_UPDATE_HOOK)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mise à jour impossible : {exc}")
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
    data = json.loads((BASE_DIR / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    if LOCAL_MODE:
        # Version PC installée comme appli d'Edge/Chrome : la page dessine sa propre barre
        # de titre, à côté des boutons de la fenêtre (voir .titlebar dans style.css).
        data["display_override"] = ["window-controls-overlay", "standalone"]
    return JSONResponse(data, media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # Servi à la racine pour que le service worker contrôle toute l'appli
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# Préférés (signet dans les listes) : format du son, format de la vidéo, qualité de la vidéo.
# Gardé par l'appli : la page, l'extension et le téléphone relié voient le même.
# ---------------------------------------------------------------------------

PREFS_FILE = STATE_DIR / "preferences.json"
PREFS_LOCK = threading.Lock()


class PreferenceRequest(BaseModel):
    kind: Literal["video", "audio", "quality"]
    # Format ("mp4"…), ou pour la qualité : hauteur ("1080") ou "" = meilleure disponible.
    # None = plus de préféré pour ce type.
    container: Optional[str] = None


def _valid_pref(kind: str, value) -> bool:
    if kind == "quality":
        return isinstance(value, str) and (value == "" or (value.isdigit() and len(value) <= 4))
    return value in (VIDEO_CONTAINERS if kind == "video" else AUDIO_CONTAINERS)


def _prefs() -> dict:
    try:
        data = json.loads(PREFS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: (data.get(k) if _valid_pref(k, data.get(k)) else None) for k in ("video", "audio", "quality")}


def set_preference(kind: str, container: Optional[str]) -> dict:
    """Retient (ou enlève, avec None) le préféré d'un type. Renvoie tous les préférés."""
    if kind not in ("video", "audio", "quality") or (container is not None and not _valid_pref(kind, container)):
        raise ValueError("Format inconnu.")
    with PREFS_LOCK:
        prefs = _prefs()
        prefs[kind] = container
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = PREFS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(prefs), "utf-8")
            tmp.replace(PREFS_FILE)
        except OSError as exc:
            raise ValueError(f"Réglage impossible : {exc}")
    return prefs


@app.get("/api/preferences")
async def get_preferences():
    return JSONResponse(_prefs(), headers={"Cache-Control": "no-cache"})


@app.post("/api/preferences")
async def save_preference(payload: PreferenceRequest):
    try:
        return set_preference(payload.kind, payload.container)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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


YTDLP_RESTART_MSG = ("Le site a refusé l'accès (403). Une version plus récente de yt-dlp est prête : "
                     "ferme puis relance MediaVior, et réessaie.")


def _ytdlp_waiting() -> bool:
    """Appli PC : une version plus récente de yt-dlp est téléchargée mais pas encore chargée."""
    try:
        cur = json.loads((STATE_DIR / "yt-dlp" / "actuel.json").read_text("utf-8"))
        return _version_tuple(cur.get("version", "0")) > _version_tuple(yt_dlp.version.__version__)
    except (OSError, ValueError, AttributeError):
        return False


def _humanize_error(exc: Exception) -> str:
    raw = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    for pattern, message in ERROR_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            if pattern.startswith("http error 403") and LOCAL_MODE and _ytdlp_waiting():
                return YTDLP_RESTART_MSG
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


def _media_file(d: Path, meta: Optional[dict] = None) -> Optional[Path]:
    meta = _read_meta(d) if meta is None else meta
    if meta.get("file"):  # média fini : dossier principal, ou celui des sons / des vidéos
        media = Path(meta["dir"]) / meta["file"] if meta.get("dir") else DOWNLOAD_DIR / meta["file"]
        return media if media.is_file() else None
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
    media = _media_file(d, meta)
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


def _free_name(name: str, folder: Optional[Path] = None) -> Path:
    """Nom libre dans le dossier principal : « Titre.mp3 », sinon « Titre (2).mp3 »…"""
    folder = folder or DOWNLOAD_DIR
    target, n = folder / name, 2
    while target.exists():
        target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return target


def _folder_for(media: Path) -> Path:
    """Dossier où ranger ce média : celui des sons, celui des vidéos, sinon le principal (zips…)."""
    ext = media.suffix.lower()
    if ext in AUDIO_EXTS and AUDIO_DIR:
        return AUDIO_DIR
    if ext not in AUDIO_EXTS and ext != ".zip" and VIDEO_DIR:
        return VIDEO_DIR
    return DOWNLOAD_DIR


def _publish(d: Path) -> Optional[Path]:
    """Sort le média fini de son dossier de travail et le range directement dans le dossier
    principal (ou celui des sons / des vidéos), à côté des autres. Sa fiche retient où."""
    meta = _read_meta(d)
    media = _media_file(d, meta)
    if not media or meta.get("file"):
        return media
    folder = _folder_for(media)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = DOWNLOAD_DIR  # disque débranché… : dossier principal
    target = _free_name(media.name, folder)
    shutil.move(str(media), str(target))
    meta.setdefault("status", "done")  # anciens médias sans fiche
    meta["file"] = target.name
    if folder != DOWNLOAD_DIR:
        meta["dir"] = str(folder)
    else:
        meta.pop("dir", None)
    _write_meta(d, meta)
    return target


def _item_dir(item_id: str) -> Path:
    if not ITEM_ID.match(item_id):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    d = ITEMS_DIR / item_id
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return d


def _item_or_404(item_id: str) -> dict:
    item = _item_view(_item_dir(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Fichier pas encore prêt")
    return item


def _cleanup_unfinished() -> None:
    """Au démarrage : range les médias de l'ancienne version (un sous-dossier par média),
    supprime les jobs interrompus par un redémarrage et les fiches dont le média a été effacé."""
    old_sons = DOWNLOAD_DIR / ".liste-sons.json"
    if old_sons.is_file() and not SONS_FILE.exists():
        old_sons.replace(SONS_FILE)
    for d in DOWNLOAD_DIR.iterdir():
        if d.is_dir() and ITEM_ID.match(d.name) and not (ITEMS_DIR / d.name).exists():
            try:
                d.replace(ITEMS_DIR / d.name)
            except OSError:
                pass  # fichier ouvert ailleurs : on réessaiera au prochain lancement
    for d in ITEMS_DIR.iterdir():
        if not (d.is_dir() and ITEM_ID.match(d.name)):
            continue
        meta = _read_meta(d)
        if meta and meta.get("status") != "done":
            shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            if not _publish(d):
                shutil.rmtree(d, ignore_errors=True)  # média supprimé depuis l'explorateur
        except OSError:
            pass
    for folder in (ITEMS_DIR, DOWNLOAD_DIR):  # zips de sélection pas encore effacés
        for z in folder.glob(".selection-*.zip"):
            z.unlink(missing_ok=True)


def _read_history() -> dict:
    try:
        data = json.loads(HISTORY_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_history(history: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False), "utf-8")
        tmp.replace(HISTORY_FILE)
    except OSError:
        pass  # les stats attendront la prochaine fois


def _remember(items: list) -> None:
    """Note chaque média du coffre dans l'historique (ajouts et tailles à jour)."""
    with HISTORY_LOCK:
        history = _read_history()
        changed = False
        for i in items:
            entry = {"mode": i["mode"], "size": i["size"], "duration": i.get("duration") or 0,
                     "created": i["created"]}
            if history.get(i["id"]) != entry:
                history[i["id"]] = entry
                changed = True
        if changed:
            _write_history(history)


def _forget(item_id: str) -> None:
    with HISTORY_LOCK:
        history = _read_history()
        if history.pop(item_id, None) is not None:
            _write_history(history)


@app.get("/api/library")
async def library():
    items = [
        item for d in ITEMS_DIR.iterdir()
        if d.is_dir() and ITEM_ID.match(d.name) and (item := _item_view(d))
    ]
    items.sort(key=lambda i: i["created"], reverse=True)
    await asyncio.get_running_loop().run_in_executor(None, _remember, items)
    return items


@app.get("/api/stats")
async def stats():
    """Stats du coffre : tout ce qui a été téléchargé, même si les fichiers ont été déplacés
    ailleurs depuis. Seul « Enlever du coffre » dans l'appli retire un média des stats."""
    with HISTORY_LOCK:
        entries = list(_read_history().values())
    count = {"audio": 0, "video": 0, "archive": 0}
    for e in entries:
        count[e.get("mode")] = count.get(e.get("mode"), 0) + 1
    return {
        "total": len(entries),
        "audio": count["audio"], "video": count["video"], "archive": count["archive"],
        "size": sum(e.get("size") or 0 for e in entries),
        "duration": sum(e.get("duration") or 0 for e in entries),
        "last": max((e.get("created") or 0 for e in entries), default=None),
    }


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
    media = _media_file(_item_dir(item_id))
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
    meta = _read_meta(d)
    media = _media_file(d, meta)
    if media and meta.get("file"):  # média rangé (dossier principal, sons ou vidéos)
        media.unlink(missing_ok=True)
    shutil.rmtree(d, ignore_errors=True)
    JOBS.pop(item_id, None)
    _forget(item_id)
    return {"ok": True}


@app.get("/api/file/{item_id}")
async def get_file(item_id: str, inline: bool = False):
    item = _item_or_404(item_id)
    return FileResponse(
        _media_file(_item_dir(item_id)),
        filename=item["filename"],
        content_disposition_type="inline" if inline else "attachment",
    )


def _zip_items(items: list) -> Path:
    fd, tmp = tempfile.mkstemp(prefix=".selection-", suffix=".zip", dir=ITEMS_DIR)
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
            zf.write(_media_file(ITEMS_DIR / item["id"]), name)
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
    d = ITEMS_DIR / item_id
    png = d / ".waveform.png"
    if not png.exists():
        ok = await asyncio.get_running_loop().run_in_executor(None, _make_waveform, _media_file(d), png)
        if not ok:
            raise HTTPException(status_code=404, detail="Pas de piste audio")
    return FileResponse(png, media_type="image/png")


# ---------------------------------------------------------------------------
# Infos des morceaux (titre, interprètes, album…) : lire, chercher, corriger
# ---------------------------------------------------------------------------
# Sources gratuites et sans compte : MusicBrainz (base musicale libre, pochettes sur Cover Art
# Archive) et Deezer en secours (sorties récentes, rap FR…). Les infos sont écrites dans le
# fichier avec mutagen (MP3, AIFF, WAV, FLAC, M4A, Opus, Ogg).

TAG_FIELDS = ("title", "artist", "album", "album_artist", "year", "genre", "track")
_ID3_FRAMES = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "album_artist": "TPE2",
               "year": "TDRC", "genre": "TCON", "track": "TRCK"}
_MP4_KEYS = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "album_artist": "aART",
             "year": "\xa9day", "genre": "\xa9gen"}
_VORBIS_KEYS = {"title": "title", "artist": "artist", "album": "album", "album_artist": "albumartist",
                "year": "date", "genre": "genre", "track": "tracknumber"}
# ffprobe : noms des champs quand mutagen ne lit rien (WAV avec étiquettes RIFF, par exemple)
_PROBE_KEYS = {"title": "title", "artist": "artist", "album": "album", "album_artist": "album_artist",
               "year": "date", "genre": "genre", "track": "track"}
MAX_IMPORT_BYTES = 2 * 1024 ** 3  # 2 Go par fichier : large, même pour un long WAV
MAX_COVER_BYTES = 8 * 1024 * 1024
# Pochettes : seulement depuis ces sites (jamais une adresse choisie par la page)
COVER_HOSTS = ("coverartarchive.org", "archive.org", "dzcdn.net")
TAGS_UA = f"{APP_NAME}/1.0 ( {GITHUB_URL} )"  # MusicBrainz demande un nom d'appli et un contact
_MB_LOCK = threading.Lock()  # MusicBrainz : une requête par seconde au plus
_MB_LAST = [0.0]


class TagsRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=300)
    artist: Optional[str] = Field(None, max_length=300)
    album: Optional[str] = Field(None, max_length=300)
    album_artist: Optional[str] = Field(None, max_length=300)
    year: Optional[str] = Field(None, max_length=10)
    genre: Optional[str] = Field(None, max_length=120)
    track: Optional[str] = Field(None, max_length=10)
    cover_url: Optional[str] = Field(None, max_length=500)
    rename: bool = False


def _mutagen_file(path: Path):
    import mutagen
    try:
        return mutagen.File(str(path))
    except Exception:
        return None


def _first(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, tuple):  # trkn des M4A : (numéro, total)
        value = value[0] or ""
    return str(value).strip()


def _read_tags(path: Path) -> dict:
    """Infos écrites dans le fichier, plus la présence d'une pochette."""
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4Tags
    tags = {k: "" for k in TAG_FIELDS}
    cover = False
    f = _mutagen_file(path)
    t = getattr(f, "tags", None) if f is not None else None
    if isinstance(t, ID3):
        for key, frame in _ID3_FRAMES.items():
            if frame in t:
                tags[key] = ", ".join(str(x) for x in t[frame].text if str(x).strip())
        cover = bool(t.getall("APIC"))
    elif isinstance(t, MP4Tags):
        for key, name in _MP4_KEYS.items():
            tags[key] = _first(t.get(name))
        tags["track"] = _first(t.get("trkn"))
        cover = bool(t.get("covr"))
    elif t is not None:  # FLAC, Opus, Ogg : commentaires Vorbis
        for key, name in _VORBIS_KEYS.items():
            tags[key] = ", ".join(v for v in (t.get(name) or []) if v.strip())
        cover = bool(getattr(f, "pictures", None)) or bool(t.get("metadata_block_picture"))
    if not any(tags.values()):  # rien de lisible par mutagen : ffprobe (étiquettes RIFF des WAV…)
        try:
            out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            found = {k.lower(): v for k, v in ((json.loads(out.stdout or "{}").get("format") or {}).get("tags") or {}).items()}
            for key, name in _PROBE_KEYS.items():
                tags[key] = str(found.get(name) or "").strip()
        except Exception:
            pass
    tags["year"] = tags["year"][:4] if re.match(r"^\d{4}", tags["year"]) else tags["year"]
    tags["track"] = tags["track"].split("/")[0]
    return {**tags, "cover": cover}


def _read_cover(path: Path) -> Optional[tuple]:
    """Pochette intégrée au fichier : (octets, type MIME), sinon None."""
    import base64
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4Tags, MP4Cover
    from mutagen.flac import Picture
    f = _mutagen_file(path)
    t = getattr(f, "tags", None) if f is not None else None
    if isinstance(t, ID3):
        pics = t.getall("APIC")
        if pics:
            front = next((p for p in pics if p.type == 3), pics[0])
            return front.data, front.mime or "image/jpeg"
    elif isinstance(t, MP4Tags):
        covr = t.get("covr") or []
        if covr:
            return bytes(covr[0]), "image/png" if covr[0].imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
    elif t is not None:
        pics = list(getattr(f, "pictures", None) or [])
        for raw in t.get("metadata_block_picture") or []:
            try:
                pics.append(Picture(base64.b64decode(raw)))
            except Exception:
                pass
        if pics:
            return pics[0].data, pics[0].mime or "image/jpeg"
    return None


def _write_tags(path: Path, values: dict, cover: Optional[tuple] = None) -> None:
    """Écrit les infos dans le fichier. Une valeur None ne touche pas au champ, "" l'efface."""
    import base64
    from mutagen import id3
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.flac import FLAC, Picture
    from mutagen.mp3 import MP3
    from mutagen.aiff import AIFF
    from mutagen.wave import WAVE
    f = _mutagen_file(path)
    if f is None:
        raise ValueError("format non reconnu")
    if f.tags is None:
        f.add_tags()  # AAC brut : pas de place pour les infos (erreur, affichée telle quelle)
    t = f.tags
    if isinstance(t, id3.ID3):
        for key, frame in _ID3_FRAMES.items():
            if values.get(key) is None:
                continue
            t.delall(frame)
            if values[key]:
                t.add(getattr(id3, frame)(encoding=3, text=[values[key]]))
        if cover:
            t.delall("APIC")
            t.add(id3.APIC(encoding=3, mime=cover[1], type=3, desc="Cover", data=cover[0]))
        # ID3v2.3 : la version que Windows, Rekordbox, Serato et la plupart des lecteurs lisent
        f.save(v2_version=3) if isinstance(f, (MP3, AIFF, WAVE)) else f.save()
        return
    if isinstance(f, MP4):
        for key, name in _MP4_KEYS.items():
            if values.get(key) is None:
                continue
            t.pop(name, None)
            if values[key]:
                t[name] = [values[key]]
        if values.get("track") is not None:
            t.pop("trkn", None)
            if values["track"].isdigit():
                t["trkn"] = [(int(values["track"]), 0)]
        if cover:
            fmt = MP4Cover.FORMAT_PNG if cover[1] == "image/png" else MP4Cover.FORMAT_JPEG
            t["covr"] = [MP4Cover(cover[0], imageformat=fmt)]
        f.save()
        return
    for key, name in _VORBIS_KEYS.items():  # FLAC, Opus, Ogg
        if values.get(key) is None:
            continue
        if name in t:
            del t[name]
        if values[key]:
            t[name] = [values[key]]
    if cover:
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, cover[1], "Cover", cover[0]
        if isinstance(f, FLAC):
            f.clear_pictures()
            f.add_picture(pic)
        else:
            t["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    f.save()


def _norm(text: str) -> str:
    """Pour comparer deux titres : minuscules, sans accents ni ponctuation ni « (Official Video) »."""
    text = _strip_accents(_clean_title(text or "")).lower()
    text = re.sub(r"\b(feat|ft|featuring)\b.*$", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _noisy(tags: dict, filename: str) -> dict:
    """Champs vides ou mal faits : à compléter par la recherche."""
    title = tags.get("title") or ""
    return {
        "title": not title or title == Path(filename).stem or _clean_title(title) != title
        or bool(_TITLE_SPLIT.match(title) and not tags.get("artist")),
        "artist": not tags.get("artist"),
        "album": not tags.get("album"),
        "year": not tags.get("year"),
        "cover": not tags.get("cover"),
    }


def _guess(tags: dict, filename: str) -> dict:
    """« Artiste » et « Titre » probables, d'après les infos du fichier ou son nom."""
    # « (2) » : ajouté par l'appli quand le nom de fichier était déjà pris
    title = _clean_title(tags.get("title") or re.sub(r"\s\(\d+\)$", "", Path(filename).stem))
    artist = tags.get("artist") or ""
    split = _TITLE_SPLIT.match(title)
    if split and (not artist or _norm(split.group(1)) in _norm(artist) or _norm(artist) in _norm(split.group(1))):
        artist, title = artist or split.group(1).strip(), split.group(2).strip()
    title = re.sub(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", "", _clean_title(title), flags=re.IGNORECASE)
    return {"artist": _clean_channel(artist) if artist else "", "title": title.strip()}


def _http_json(url: str, timeout: int = 12) -> dict:
    from urllib.request import Request as UrlRequest
    req = UrlRequest(url, headers={"User-Agent": TAGS_UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(4 * 1024 * 1024).decode("utf-8"))


def _mb_release(recording: dict) -> dict:
    """La sortie la plus « normale » d'un enregistrement : album ou single officiel, pas une compil."""
    def rank(rel: dict) -> tuple:
        group = rel.get("release-group") or {}
        secondary = group.get("secondary-types") or []
        return (
            rel.get("status") not in (None, "Official"),
            "Compilation" in secondary or "DJ-mix" in secondary or "Live" in secondary,
            {"Album": 0, "EP": 1, "Single": 2}.get(group.get("primary-type"), 3),
            rel.get("date") or "9999",
        )
    releases = recording.get("releases") or []
    return min(releases, key=rank) if releases else {}


def _musicbrainz_search(artist: str, title: str, limit: int = 8) -> list:
    def esc(s: str) -> str:
        return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)
    query = f'recording:"{esc(title)}"' + (f' AND artist:"{esc(artist)}"' if artist else "")
    with _MB_LOCK:
        wait = 1.1 - (time.time() - _MB_LAST[0])
        if wait > 0:
            time.sleep(wait)
        try:
            data = _http_json("https://musicbrainz.org/ws/2/recording?" + urlencode(
                {"query": query, "fmt": "json", "limit": limit}))
        finally:
            _MB_LAST[0] = time.time()
    results = []
    for rec in data.get("recordings") or []:
        if (rec.get("score") or 0) < 60:
            continue
        credit = "".join(f"{c.get('name', '')}{c.get('joinphrase', '')}" for c in rec.get("artist-credit") or [])
        rel = _mb_release(rec)
        group = rel.get("release-group") or {}
        media = (rel.get("media") or [{}])[0]
        track = ((media.get("track") or [{}])[0]).get("number") or ""
        date = rel.get("date") or rec.get("first-release-date") or ""
        album_artist = "".join(f"{c.get('name', '')}{c.get('joinphrase', '')}" for c in rel.get("artist-credit") or []) or credit
        results.append({
            "source": "MusicBrainz",
            "title": rec.get("title") or "",
            "artist": credit,
            "album": rel.get("title") or "",
            "album_artist": album_artist,
            "year": date[:4],
            "track": str(track) if str(track).isdigit() else "",
            "genre": "",
            "duration": round(rec["length"] / 1000) if rec.get("length") else None,
            "cover": f"https://coverartarchive.org/release-group/{group['id']}/front-250" if group.get("id") else None,
            "cover_full": f"https://coverartarchive.org/release-group/{group['id']}/front-500" if group.get("id") else None,
        })
    return results


def _deezer_search(artist: str, title: str, limit: int = 6) -> list:
    q = f'artist:"{artist}" track:"{title}"' if artist else title
    data = _http_json("https://api.deezer.com/search?" + urlencode({"q": q, "limit": limit}))
    tracks = data.get("data") or []
    if not tracks and artist:  # recherche stricte vide : en texte libre
        data = _http_json("https://api.deezer.com/search?" + urlencode({"q": f"{artist} {title}", "limit": limit}))
        tracks = data.get("data") or []
    albums: Dict[int, dict] = {}

    def album_info(album_id: int) -> dict:  # date de sortie et genre : seulement sur la fiche de l'album
        try:
            return _http_json(f"https://api.deezer.com/album/{int(album_id)}", timeout=8)
        except Exception:
            return {}
    from concurrent.futures import ThreadPoolExecutor
    ids = list(dict.fromkeys((t.get("album") or {}).get("id") for t in tracks[:4] if (t.get("album") or {}).get("id")))
    if ids:
        with ThreadPoolExecutor(max_workers=4) as pool:
            albums = dict(zip(ids, pool.map(album_info, ids)))
    results = []
    for t in tracks:
        album = t.get("album") or {}
        info = albums.get(album.get("id")) or {}
        genres = [g.get("name") for g in ((info.get("genres") or {}).get("data") or []) if g.get("name")]
        results.append({
            "source": "Deezer",
            "title": t.get("title") or "",
            "artist": (t.get("artist") or {}).get("name") or "",
            "album": album.get("title") or "",
            "album_artist": (info.get("artist") or {}).get("name") or "",
            "year": str(info.get("release_date") or "")[:4],
            "track": "",
            "genre": ", ".join(genres[:2]),
            "duration": t.get("duration"),
            "cover": album.get("cover_medium"),
            "cover_full": album.get("cover_xl") or album.get("cover_big"),
        })
    return results


def _match_score(r: dict, artist: str, title: str, duration: Optional[float]) -> float:
    score = 0.0
    nt, na = _norm(title), _norm(artist)
    rt, ra = _norm(r["title"]), _norm(r["artist"])
    if nt and rt == nt:
        score += 3
    elif nt and (nt in rt or rt in nt):
        score += 1.5
    if na and ra and (na in ra or ra in na):
        score += 3
    if duration and r.get("duration"):
        gap = abs(r["duration"] - duration)
        score += 2 if gap <= 3 else 1 if gap <= 10 else -2 if gap > 30 else 0
    score += 0.5 * bool(r.get("album")) + 0.5 * bool(r.get("year")) + 0.3 * bool(r.get("cover"))
    return score


def _search_tags(artist: str, title: str, duration: Optional[float] = None) -> dict:
    """Résultats des deux sources, les plus ressemblants d'abord, sans doublons."""
    results, errors = [], []
    for search in (_musicbrainz_search, _deezer_search):
        try:
            results += search(artist, title)
        except Exception:
            errors.append(search.__name__)
    for r in results:
        r["score"] = round(_match_score(r, artist, title, duration), 2)
    results.sort(key=lambda r: r["score"], reverse=True)
    seen, unique = {}, []
    for r in results:
        key = (_norm(r["title"]), _norm(r["artist"]), _norm(r["album"]))
        if key in seen:  # même morceau sur les deux sources : on complète ce qui manque (genre…)
            kept = seen[key]
            for field in ("album_artist", "year", "track", "genre", "cover", "cover_full", "duration"):
                if not kept.get(field) and r.get(field):
                    kept[field] = r[field]
            kept["source"] = kept["source"] if r["source"] in kept["source"] else f"{kept['source']} + {r['source']}"
        else:
            seen[key] = r
            unique.append(r)
    return {"results": unique[:10], "offline": len(errors) == 2}


def _confident(r: dict, artist: str, title: str, duration: Optional[float]) -> bool:
    """Assez sûr pour remplir tout seul : même titre, même artiste, durée proche si on la connaît."""
    if not artist or _norm(r["title"]) != _norm(title):
        return False
    ra, na = _norm(r["artist"]), _norm(artist)
    if not (na and ra and (na in ra or ra in na)):
        return False
    return not (duration and r.get("duration") and abs(r["duration"] - duration) > 5)


def _fetch_cover(url: str) -> Optional[tuple]:
    """Télécharge une pochette, seulement depuis Cover Art Archive ou Deezer (redirections comprises)."""
    from urllib.request import HTTPRedirectHandler, Request as UrlRequest, build_opener

    def allowed(u: str) -> bool:
        p = urlparse(u)
        host = (p.hostname or "").lower()
        return p.scheme == "https" and any(host == h or host.endswith("." + h) for h in COVER_HOSTS)

    class OnlyCovers(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed(newurl):
                raise ValueError("redirection refusée")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    if not allowed(url):
        raise HTTPException(status_code=400, detail="Pochette refusée : elle ne vient pas de MusicBrainz ou Deezer.")
    try:
        with build_opener(OnlyCovers).open(UrlRequest(url, headers={"User-Agent": TAGS_UA}), timeout=20) as r:
            data = r.read(MAX_COVER_BYTES + 1)
            mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0]
    except Exception:
        return None
    if len(data) > MAX_COVER_BYTES or not mime.startswith("image/"):
        return None
    return data, "image/png" if mime == "image/png" else "image/jpeg"


def _safe_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    return re.sub(r"\s+", " ", text).strip(" .")[:150]


def _tag_title(tags: dict, fallback: str) -> str:
    if tags.get("artist") and tags.get("title"):
        return f"{tags['artist']} - {tags['title']}"
    return tags.get("title") or fallback


def _apply_tags(d: Path, values: dict, cover: Optional[tuple], rename: bool) -> dict:
    """Écrit les infos, met à jour la fiche (titre, pochette) et renomme si demandé."""
    meta = _read_meta(d)
    media = _media_file(d, meta)
    if not media:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    try:
        _write_tags(media, values, cover)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossible d'écrire les infos dans ce fichier : {exc}")
    tags = _read_tags(media)
    if rename and meta.get("file") and tags.get("title"):
        name = _safe_filename(_tag_title(tags, media.stem))
        if name and name != media.stem:
            target = _free_name(name + media.suffix, media.parent)
            media.rename(target)
            meta["file"] = target.name
    meta["title"] = _tag_title(tags, meta.get("title") or media.stem)
    if tags.get("cover"):
        meta["thumbnail"] = f"/api/library/{d.name}/cover?v={int(time.time())}"
    _write_meta(d, meta)
    return tags


def _auto_tags(media: Path, duration: Optional[float], fill_cover: bool = True) -> Optional[dict]:
    """Complète les champs vides ou mal faits si la recherche trouve le morceau à coup sûr.
    Ne remplace jamais une info déjà correcte. Renvoie les champs remplis (ou None)."""
    try:
        tags = _read_tags(media)
        guess = _guess(tags, media.name)
        if not guess["artist"] or not guess["title"]:
            return None
        found = _search_tags(guess["artist"], guess["title"], duration)["results"]
        best = next((r for r in found if _confident(r, guess["artist"], guess["title"], duration)), None)
        noisy = _noisy(tags, media.name)
        values = {}
        if best:
            for key in ("title", "artist"):
                if noisy[key] and best[key]:
                    values[key] = best[key]
            for key in ("album", "album_artist", "year", "genre", "track"):
                if not tags.get(key) and best.get(key):
                    values[key] = best[key]
        else:  # pas trouvé : au moins « Artiste » et « Titre » d'après le nom
            if noisy["title"]:
                values["title"] = guess["title"]
            if noisy["artist"]:
                values["artist"] = guess["artist"]
        cover = _fetch_cover(best["cover_full"]) if best and fill_cover and noisy["cover"] and best.get("cover_full") else None
        if not values and not cover:
            return None
        _write_tags(media, values, cover)
        return {**values, "cover": bool(cover)}
    except Exception:
        return None  # pas d'Internet, format sans infos… : le fichier reste tel quel


@app.get("/api/library/{item_id}/tags")
async def get_tags(item_id: str):
    item = _item_or_404(item_id)
    if item["mode"] != "audio":
        raise HTTPException(status_code=400, detail="Les infos du morceau ne concernent que les sons.")
    media = _media_file(_item_dir(item_id))
    tags = await asyncio.get_running_loop().run_in_executor(None, _read_tags, media)
    return {"tags": tags, "guess": _guess(tags, media.name), "noisy": _noisy(tags, media.name),
            "filename": media.name, "duration": item.get("duration")}


@app.get("/api/library/{item_id}/cover")
async def get_cover(item_id: str):
    _item_or_404(item_id)
    found = await asyncio.get_running_loop().run_in_executor(None, _read_cover, _media_file(_item_dir(item_id)))
    if not found:
        raise HTTPException(status_code=404, detail="Pas de pochette")
    return Response(content=found[0], media_type=found[1], headers={"Cache-Control": "max-age=86400"})


@app.get("/api/tags/search")
async def search_tags(artist: str = "", title: str = "", duration: Optional[float] = None):
    artist, title = artist.strip()[:200], title.strip()[:200]
    if not title:
        raise HTTPException(status_code=400, detail="Écris au moins le titre du morceau.")
    found = await asyncio.get_running_loop().run_in_executor(None, _search_tags, artist, title, duration)
    if found["offline"]:
        raise HTTPException(status_code=502, detail="Recherche impossible : MusicBrainz et Deezer ne répondent pas. Vérifie ta connexion Internet.")
    return found


@app.put("/api/library/{item_id}/tags")
async def save_tags(item_id: str, payload: TagsRequest):
    item = _item_or_404(item_id)
    if item["mode"] != "audio":
        raise HTTPException(status_code=400, detail="Les infos du morceau ne concernent que les sons.")
    job = JOBS.get(item_id)
    if job and job["status"] in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Ce fichier est encore en cours de traitement.")
    # Champ absent : laissé tel quel ; champ vide : effacé
    values = {k: (v.strip() if (v := getattr(payload, k)) is not None else None) for k in TAG_FIELDS}
    loop = asyncio.get_running_loop()
    cover = None
    if payload.cover_url:
        cover = await loop.run_in_executor(None, _fetch_cover, payload.cover_url)
        if not cover:
            raise HTTPException(status_code=502, detail="Impossible de récupérer cette pochette. Réessaie, ou enregistre sans.")
    d = _item_dir(item_id)
    tags = await loop.run_in_executor(None, _apply_tags, d, values, cover, payload.rename)
    return {"tags": tags, "item": _item_view(d)}


@app.post("/api/library/import")
async def import_file(request: Request, name: str, auto: bool = True):
    """Ajoute un fichier son de l'ordinateur au coffre (corps brut de la requête = le fichier),
    puis complète ses infos si la recherche trouve le morceau à coup sûr."""
    name = _safe_filename(Path(name).name)
    ext = Path(name).suffix.lower()
    if not name or ext not in AUDIO_EXTS:
        raise HTTPException(status_code=400, detail="Seuls les fichiers son sont acceptés (MP3, AIFF, WAV, FLAC, M4A, Opus, Ogg).")
    item_id = uuid.uuid4().hex
    d = ITEMS_DIR / item_id
    d.mkdir(parents=True)
    tmp = d / name
    size = 0
    try:
        with tmp.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_IMPORT_BYTES:
                    raise HTTPException(status_code=413, detail="Fichier trop lourd (2 Go maximum).")
                out.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        loop = asyncio.get_running_loop()
        try:
            probe = await loop.run_in_executor(None, _probe, tmp)
        except Exception:
            probe = {}
        if not probe.get("has_audio"):
            raise HTTPException(status_code=400, detail="Ce fichier ne contient pas de son lisible.")
        filled = await loop.run_in_executor(None, _auto_tags, tmp, probe.get("duration")) if auto else None
        tags = await loop.run_in_executor(None, _read_tags, tmp)
        meta = {"status": "done", "kind": "import", "title": _tag_title(tags, tmp.stem),
                "created": time.time(), "duration": probe.get("duration") or None}
        if tags.get("cover"):
            meta["thumbnail"] = f"/api/library/{item_id}/cover?v={int(time.time())}"
        _write_meta(d, meta)
        await loop.run_in_executor(None, _publish, d)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return {"item": _item_view(d), "filled": filled}


def _auto_album(media: Optional[Path], duration: Optional[float]) -> None:
    """Après un téléchargement de son : l'album, l'année d'origine… si la recherche est sûre.
    La pochette de la vidéo reste (elle est déjà dans le fichier)."""
    if media and media.suffix.lower() in AUDIO_EXTS and media.suffix.lower() != ".aac":
        _auto_tags(media, duration, fill_cover=False)


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------

# Erreur 403 : souvent un cache yt-dlp périmé, ou YouTube qui bloque un « client » précis.
# On réessaie alors une fois, cache vidé, avec d'autres clients YouTube (sans effet ailleurs).
# Un nom de client inconnu d'une future version de yt-dlp est simplement ignoré.
RETRY_403_CLIENTS = ["tv", "web_safari", "android_vr", "web_embedded"]


def _is_403(exc: Exception) -> bool:
    return bool(re.search(r"http error 403|403:? forbidden", str(exc), re.IGNORECASE))


# Son : le fichier sans perte d'abord quand le site en fournit un (Bandcamp gratuit ou à prix libre,
# Jamendo, Archive.org, fichier de l'artiste sur SoundCloud…), sinon la meilleure piste du site.
LOSSLESS_CODECS = r"^(flac|alac|wav|aiff|pcm)"
AUDIO_FORMAT = f"bestaudio[acodec~='{LOSSLESS_CODECS}']/bestaudio/best"

# « Utiliser ma connexion du navigateur » (version PC) : yt-dlp lit sur l'ordinateur les cookies
# du navigateur choisi. Débloque YouTube Premium (256 kb/s) et le fichier de l'artiste sur SoundCloud.
# Rien n'est envoyé ailleurs qu'au site du média.
LOGIN_FILE = STATE_DIR / "connexion.json"
LOGIN_BROWSERS = ("firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium", "safari")
LOGIN_STATE = {"error": None}  # dernière lecture ratée des cookies (affichée dans les Réglages)


def _login_browser() -> Optional[str]:
    if not LOCAL_MODE:
        return None
    try:
        browser = json.loads(LOGIN_FILE.read_text("utf-8")).get("browser")
    except (OSError, ValueError, AttributeError):
        return None
    return browser if browser in LOGIN_BROWSERS else None


def _set_login_browser(browser: Optional[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LOGIN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"browser": browser}), "utf-8")
    tmp.replace(LOGIN_FILE)
    LOGIN_STATE["error"] = None


def _open_ydl(opts: dict):
    """YoutubeDL avec la connexion du navigateur si elle est choisie. Si les cookies ne se lisent pas
    (navigateur fermé à clé, chiffrement…), on continue sans, et l'erreur s'affiche dans les Réglages."""
    browser = _login_browser()
    if browser:
        ydl = yt_dlp.YoutubeDL({**opts, "cookiesfrombrowser": (browser,)})
        try:
            ydl.cookiejar  # lit les cookies tout de suite
            LOGIN_STATE["error"] = None
            return ydl
        except Exception as exc:
            ydl.close()
            LOGIN_STATE["error"] = re.sub(r"^ERROR:\s*", "", str(exc))[:300]
    return yt_dlp.YoutubeDL(opts)


def _run_ytdlp(opts: dict, run, clean: Optional[Path] = None):
    """Lance run(ydl) ; après un refus 403, réessaie une fois. clean : dossier où effacer les .part."""
    try:
        with _open_ydl(opts) as ydl:
            return run(ydl)
    except JobCancelled:
        raise
    except Exception as exc:
        if not _is_403(exc):
            raise
    if clean:  # morceaux du premier essai : leurs adresses ne sont plus valables
        for f in clean.glob("*.part*"):
            f.unlink(missing_ok=True)
    retry = {**opts, "extractor_args": {"youtube": {"player_client": RETRY_403_CLIENTS}}}
    with _open_ydl(retry) as ydl:
        ydl.cache.remove()
        return run(ydl)


def _extract_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",  # une playlist répond vite au lieu d'analyser chaque vidéo
    }
    return _run_ytdlp(ydl_opts, lambda ydl: ydl.extract_info(url, download=False))


def _format_size(f: dict, duration: Optional[float]) -> Optional[float]:
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return size


CODEC_NAMES = {"mp4a": "AAC", "aac": "AAC", "opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3", "flac": "FLAC",
               "alac": "ALAC", "wav": "WAV", "aiff": "AIFF", "pcm": "WAV", "ec-3": "E-AC-3", "ac-3": "AC-3"}


def _is_preview(f: dict) -> bool:
    return "preview" in str(f.get("format_id") or "") or (f.get("preference") or 0) <= -10


def _best_audio(formats: list) -> Optional[dict]:
    """La piste son que AUDIO_FORMAT va prendre : codec, débit, sans perte ou non.
    Les formats de yt-dlp sont rangés du moins bon au meilleur."""
    # Extraits de 30 s (SoundCloud Go+…) : seulement s'il n'y a rien d'autre
    full = [f for f in formats if not _is_preview(f)]
    with_audio = [f for f in (full or formats) if f.get("acodec") not in (None, "none")]
    audio_only = [f for f in with_audio if f.get("vcodec") == "none"]
    lossless = [f for f in audio_only if re.match(LOSSLESS_CODECS, str(f.get("acodec")))]
    best = (lossless or audio_only or with_audio or [None])[-1]
    if not best:
        return None
    acodec = str(best.get("acodec") or best.get("ext") or "")
    key = acodec.split(".")[0].split("_")[0].lower()
    kbps = best.get("abr") or (best.get("tbr") if best.get("vcodec") == "none" else None)
    return {
        "codec": CODEC_NAMES.get(key) or key.upper() or None,
        "kbps": round(kbps) if kbps else None,
        "lossless": bool(lossless),
        "note": best.get("format_note") or None,
    }


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
    url = await _expand_link(await _safe_url(payload.url))
    site = _source_site(url)
    if site:  # Qobuz, Deezer, Spotify : protégés par DRM, yt-dlp n'y arrive pas
        service = _streamrip_service(url)
        if not service:
            raise HTTPException(status_code=400, detail=_source_problem(site, url))
        return await asyncio.get_running_loop().run_in_executor(None, _source_analysis, service, url)
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
        "audio_best": _best_audio(info.get("formats") or []),
        "login": bool(_login_browser()),
        "search": _music_query(info),
    }


# ---------------------------------------------------------------------------
# Meilleure source : le même titre sur un site qui compresse moins (Bandcamp, SoundCloud).
# La personne choisit dans la liste : un résultat peut être un remix ou un autre morceau.
# ---------------------------------------------------------------------------

NOISE_WORDS = re.compile(
    r"[\(\[][^)\]]*(official|officiel|video|vidéo|clip|audio|lyrics?|paroles|visuali[sz]er|hd|4k|hq|"
    r"remaster(ed)?|live|en direct)[^)\]]*[\)\]]", re.IGNORECASE)


def _music_query(info: dict) -> str:
    """« Artiste Titre » pour chercher ailleurs, sans « (Official Video) » et compagnie."""
    track, artist = info.get("track"), info.get("artist") or info.get("creator")
    if track and artist:
        return f"{artist.split(',')[0]} {track}"[:150]
    title = NOISE_WORDS.sub(" ", info.get("title") or "")
    title = re.sub(r"\s+", " ", re.sub(r"[|•]+", " ", title)).strip(" -")
    return title[:150]


class BetterSourceRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    url: Optional[str] = None  # lien actuel, à ne pas reproposer
    duration: Optional[float] = None  # durée du média actuel : écarte les morceaux trop différents


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BANDCAMP_TRACK = re.compile(r"https://[a-z0-9-]+\.bandcamp\.com/track/[A-Za-z0-9_-]+")


def _bandcamp_search(query: str, count: int = 4) -> list:
    """Page de recherche de Bandcamp (titres seulement), puis son API de recherche en secours."""
    from urllib.parse import quote_plus
    from urllib.request import Request as UrlRequest
    urls: List[str] = []
    try:
        req = UrlRequest(f"https://bandcamp.com/search?q={quote_plus(query)}&item_type=t",
                         headers={"User-Agent": BROWSER_UA, "Accept-Language": "en"})
        with urlopen(req, timeout=12) as r:
            page = r.read().decode("utf-8", "replace")
        urls = BANDCAMP_TRACK.findall(page)
    except Exception:
        pass
    if not urls:
        body = json.dumps({"search_text": query, "search_filter": "t", "fan_id": None, "full_page": False}).encode()
        req = UrlRequest("https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic", data=body,
                         headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA,
                                  "Origin": "https://bandcamp.com", "Referer": "https://bandcamp.com/"})
        with urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        for e in ((data.get("auto") or {}).get("results") or []):
            link = e.get("item_url_path") or e.get("item_url_root")
            if e.get("type") == "t" and isinstance(link, str) and link.startswith("https://"):
                urls.append(link)
    return list(dict.fromkeys(urls))[:count]


def _soundcloud_search(query: str, count: int = 6) -> list:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"scsearch{count}:{query}", download=False) or {}
    return [e["url"] for e in info.get("entries") or [] if e and isinstance(e.get("url"), str)][:count]


def _source_details(url: str) -> Optional[dict]:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    try:
        with _open_ydl(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except Exception:
        return None
    formats = info.get("formats") or []
    if formats and all(_is_preview(f) for f in formats):
        return None  # extrait de 30 s seulement (titre réservé aux abonnés)
    best = _best_audio(formats)
    if not best:
        return None
    return {
        "url": info.get("webpage_url") or url,
        "site": info.get("extractor_key") or "",
        "title": info.get("track") or info.get("title") or url,
        "artist": info.get("artist") or info.get("uploader") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "quality": best,
    }


def _close_duration(d: Optional[float], ref: Optional[float]) -> bool:
    return not d or not ref or abs(d - ref) <= max(20, ref * 0.15)


def _better_sources(query: str, current: Optional[str], duration: Optional[float] = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    searches = {"Bandcamp": _bandcamp_search, "SoundCloud": _soundcloud_search}
    urls, failed = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = {name: pool.submit(fn, query) for name, fn in searches.items()}
        for name, fut in found.items():
            try:
                urls += fut.result(timeout=25)
            except Exception:
                failed.append(name)
        urls = [u for u in dict.fromkeys(urls) if u != current]
        details = [d for d in pool.map(_source_details, urls) if d]
    # Autre version (mix d'une heure, extrait…) : durée trop éloignée du média actuel
    kept = [d for d in details if _close_duration(d["duration"], duration)]
    hidden = len(details) - len(kept)
    details = kept
    # Sans perte d'abord, puis le débit le plus haut
    details.sort(key=lambda d: (not d["quality"]["lossless"], -(d["quality"]["kbps"] or 0)))
    return {"query": query, "results": details, "failed": failed, "hidden": hidden}


@app.post("/api/meilleure-source")
async def better_source(payload: BetterSourceRequest):
    return await asyncio.get_running_loop().run_in_executor(
        None, _better_sources, payload.query.strip(), payload.url, payload.duration)


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
        "note": None,  # remarque affichée à la fin (ex. : MP3 à la place du FLAC)
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
            media = await loop.run_in_executor(None, _publish, ITEMS_DIR / job_id)
            if media:
                job["filename"] = media.name
            job.update(status="done", progress=100, speed=None, eta=None)
        except Exception as exc:
            if job["_cancel"] or isinstance(exc, JobCancelled):
                job["status"] = "cancelled"
            else:
                job.update(status="error", error=_humanize_error(exc))
            shutil.rmtree(ITEMS_DIR / job_id, ignore_errors=True)
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
        shutil.rmtree(ITEMS_DIR / job_id, ignore_errors=True)
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


def _wav_to_aiff(folder: Path) -> None:
    """AIFF (logiciels DJ, CDJ) : yt-dlp ne sait pas le produire. On part du WAV qu'il a fait,
    puis ffmpeg écrit l'AIFF avec titre, artiste et pochette (étiquettes ID3), sans perte."""
    wav = next((f for f in folder.iterdir() if f.suffix.lower() == ".wav"), None)
    if not wav:
        return
    cover = next((f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS), None)
    out = wav.with_suffix(".aiff")
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(wav)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    cmd += ["-c:a", "pcm_s16be", "-write_id3v2", "1", "-id3v2_version", "3", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if result.returncode != 0 and cover:  # pochette refusée : l'AIFF sans pochette plutôt qu'un échec
        cmd = [FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(wav), "-c:a", "pcm_s16be",
               "-write_id3v2", "1", "-id3v2_version", "3", str(out)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"La conversion a échoué : {result.stderr.strip()[-300:]}")
    wav.unlink(missing_ok=True)


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
    url = await _expand_link(await _safe_url(payload.url))
    _check_format(payload.mode, payload.container, payload.quality, payload.audio_quality)
    if _source_site(url) and payload.mode == "video":
        raise HTTPException(status_code=400, detail="Ce lien ne donne que du son : choisis « Audio ».")

    data = payload.model_dump()
    data["url"] = url
    job = _new_job("download", payload.title or url, payload.thumbnail, data)
    job_dir = ITEMS_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {
        "status": "queued", "kind": "download", "url": url, "title": payload.title,
        "thumbnail": payload.thumbnail, "created": job["created"],
    })
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


# ---------------------------------------------------------------------------
# Sources avec abonnement (version PC) : streamrip (Qobuz, Deezer) et Votify (Spotify)
# ---------------------------------------------------------------------------
# Un lien de morceau Qobuz ou Deezer est confié à streamrip (FLAC), un lien de morceau Spotify à
# Votify (OGG Vorbis jusqu'à 320 kb/s, le fichier d'origine de Spotify, avec un compte Premium), si
# l'outil est installé et ses identifiants dans les Réglages. Sinon, ou en cas d'échec, yt-dlp reste
# le moteur. SoundCloud, albums et listes : yt-dlp. Ces options peuvent aller contre les conditions
# des sites : la page demande un accord explicite (accept_risks) avant chaque activation.
# Les identifiants restent dans `streamrip.json` à côté de l'historique, jamais renvoyés à la page.
STREAMRIP_FILE = STATE_DIR / "streamrip.json"
STREAMRIP_CONFIG = STATE_DIR / "streamrip" / "config.toml"
TOOL_TIMEOUT = 20 * 60
_TRACK_LINKS = {
    "qobuz": (re.compile(r"(^|\.)qobuz\.com$"), re.compile(r"/track/")),
    "deezer": (re.compile(r"(^|\.)deezer\.com$"), re.compile(r"/track/\d+")),
    "spotify": (re.compile(r"^open\.spotify\.com$"), re.compile(r"/track/[a-z0-9]+")),
}


def _tool_bin(name: str) -> Optional[str]:
    """Commande rip / votify : installée par mediavior.py (venv, ou uv dans l'appli installée)."""
    # Environnement propre à l'outil (installé par mediavior.py --outils et à chaque mise à jour),
    # sinon celui de l'appli, sinon pipx : streamrip et Votify ne tiennent pas ensemble
    here = Path(sys.executable).parent
    own = STATE_DIR / "outils" / name
    for exe in (name, f"{name}.exe"):
        for folder in (STATE_DIR / "outils" / "bin", own / "bin", own / "Scripts", here, here / "Scripts",
                       Path.home() / ".local" / "bin"):
            if (folder / exe).is_file():
                return str(folder / exe)
    return shutil.which(name)


def _streamrip_creds() -> dict:
    try:
        data = json.loads(STREAMRIP_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _private_write(path: Path, text: str) -> None:
    """Fichier avec des identifiants : lisible par la seule personne."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)


def _streamrip_save(creds: dict) -> None:
    _private_write(STREAMRIP_FILE, json.dumps(creds))


def _streamrip_state() -> Optional[dict]:
    """None : ni streamrip ni Votify n'est installé ici (le réglage n'apparaît pas)."""
    if not LOCAL_MODE:
        return None
    rip, votify = bool(_tool_bin("rip")), bool(_tool_bin("votify"))
    if not (rip or votify):
        return None
    c = _streamrip_creds()
    return {"streamrip": rip, "votify": votify,
            "qobuz": c.get("qobuz_email") if rip and c.get("qobuz_password") else None,
            "deezer": rip and bool(c.get("deezer_arl")),
            "spotify": votify and bool(c.get("spotify_sp_dc"))}


def _streamrip_service(url: str) -> Optional[str]:
    """qobuz / deezer / spotify si c'est un morceau et que l'outil est prêt, sinon None (→ yt-dlp)."""
    state = _streamrip_state()
    if not state:
        return None
    parts = urlparse(url)
    host, path = (parts.hostname or "").lower(), parts.path.lower()
    for service, (host_re, path_re) in _TRACK_LINKS.items():
        if host_re.search(host) and path_re.search(path) and state[service]:
            return service
    return None


_STREAMRIP_EDIT = """
import json, sys, tomlkit
path, values = sys.argv[1], json.loads(sys.argv[2])
conf = tomlkit.parse(open(path, encoding="utf-8").read())
for section, items in values.items():
    conf[section].update(items)
open(path, "w", encoding="utf-8").write(tomlkit.dumps(conf))
"""


_SITE_NAMES = {"qobuz": "Qobuz", "deezer": "Deezer", "spotify": "Spotify"}
# Liens de partage courts : on suit la redirection pour trouver le vrai lien du morceau
_SHORT_LINK_HOSTS = {"link.deezer.com", "deezer.page.link", "spotify.link", "spoti.fi"}


def _expand_link_sync(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in _SHORT_LINK_HOSTS:
        return url
    from urllib.request import Request as UrlRequest
    try:
        with urlopen(UrlRequest(url, headers={"User-Agent": BROWSER_UA}), timeout=12) as r:
            return r.geturl() or url
    except Exception:
        return url


async def _expand_link(url: str) -> str:
    """Lien court Deezer / Spotify → lien complet (vérifié à nouveau par _safe_url)."""
    final = await asyncio.get_running_loop().run_in_executor(None, _expand_link_sync, url)
    return url if final == url else await _safe_url(final)


def _source_site(url: str) -> Optional[str]:
    """qobuz / deezer / spotify si le lien vient d'un de ces sites (morceau ou non)."""
    host = (urlparse(url).hostname or "").lower()
    for service, (host_re, _) in _TRACK_LINKS.items():
        if host_re.search(host) or (service == "spotify" and host.endswith(".spotify.com")):
            return service
    return None


def _source_problem(service: str, url: str) -> str:
    """Pourquoi ce lien Qobuz / Deezer / Spotify ne peut pas être téléchargé ici (yt-dlp n'y arrive pas : DRM)."""
    name = _SITE_NAMES[service]
    if not LOCAL_MODE:
        return (f"Lien {name} : protégé par DRM. Seule la version PC de MediaVior peut le télécharger, "
                "avec ton abonnement (Réglages, Sources avec abonnement).")
    if not _TRACK_LINKS[service][1].search(urlparse(url).path.lower()):
        return f"Lien {name} : seuls les liens de morceaux marchent, pas les albums ni les listes."
    state = _streamrip_state() or {}
    if not state.get("votify" if service == "spotify" else "streamrip"):
        return (f"Lien {name} : l'outil qui le télécharge n'est pas encore installé. Il s'installe tout seul "
                "en arrière-plan : réessaie dans quelques minutes, ou relance MediaVior.")
    return f"Lien {name} : règle d'abord ton compte dans les Réglages (Sources avec abonnement)."


def _source_analysis(service: str, url: str) -> dict:
    """Infos affichées avant le téléchargement, sans yt-dlp : API publique de Deezer, oEmbed de Spotify."""
    from urllib.parse import quote
    from urllib.request import Request as UrlRequest
    info = {"title": None, "thumbnail": None, "duration": None, "artist": None}
    try:
        if service == "deezer":
            track_id = re.search(r"/track/(\d+)", urlparse(url).path).group(1)
            with urlopen(UrlRequest(f"https://api.deezer.com/track/{track_id}",
                                    headers={"User-Agent": BROWSER_UA}), timeout=12) as r:
                d = json.load(r)
            info.update(title=d.get("title"), duration=d.get("duration"),
                        artist=(d.get("artist") or {}).get("name"),
                        thumbnail=(d.get("album") or {}).get("cover_xl"))
        elif service == "spotify":
            with urlopen(UrlRequest(f"https://open.spotify.com/oembed?url={quote(url, safe='')}",
                                    headers={"User-Agent": BROWSER_UA}), timeout=12) as r:
                d = json.load(r)
            info.update(title=d.get("title"), thumbnail=d.get("thumbnail_url"))
    except Exception:
        pass  # infos absentes : le téléchargement marche quand même
    title = info["title"] or f"Morceau {_SITE_NAMES[service]}"
    if info["artist"]:
        title = f"{info['artist']} - {title}"
    lossless = service != "spotify"
    return {
        "url": url, "title": title, "thumbnail": info["thumbnail"], "duration": info["duration"],
        "source": _SITE_NAMES[service], "video_formats": [], "audio_size": None,
        "audio_best": {"codec": "FLAC" if lossless else "Vorbis", "kbps": None if lossless else 320,
                       "lossless": lossless, "note": None},
        # Spotify compresse : chercher un fichier sans perte ailleurs garde un sens
        "login": False, "search": title if info["title"] and not lossless else None, "audio_only": True,
    }


def _streamrip_write_config(folder: Path, deezer_quality: int = 2) -> Path:
    """Écrit la config de streamrip (dossier du travail, identifiants, qualité Deezer : 2 = FLAC, 1 = MP3 320). tomlkit vient avec streamrip :
    c'est le Python de streamrip (son propre environnement) qui modifie le fichier."""
    rip = Path(_tool_bin("rip"))
    STREAMRIP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not STREAMRIP_CONFIG.is_file():
        subprocess.run([str(rip), "--config-path", str(STREAMRIP_CONFIG), "config", "reset", "-y"],
                       capture_output=True, timeout=60, check=False)
    c = _streamrip_creds()
    values = {
        "downloads": {"folder": str(folder), "source_subdirectories": False},
        "qobuz": {"quality": 4, "use_auth_token": False, "email_or_userid": c.get("qobuz_email", ""),
                  "password_or_token": c.get("qobuz_password", ""), "download_booklets": False},
        "deezer": {"quality": deezer_quality, "arl": c.get("deezer_arl", "")},
        "artwork": {"embed": True, "save_artwork": False},
        "filepaths": {"add_singles_to_folder": False},
        "conversion": {"enabled": False},
        "misc": {"check_for_updates": False},
        "cli": {"progress_bars": False, "text_output": False},
    }
    # Python de streamrip : à côté de rip (venv), ou dans l'environnement créé par uv (appli installée)
    uv_env = STATE_DIR / "outils" / "uv" / "streamrip"
    candidates = [rip.resolve().parent / "python.exe", rip.resolve().parent / "python",
                  uv_env / "Scripts" / "python.exe", uv_env / "bin" / "python"]
    python = next((p for p in candidates if p.is_file()), Path(sys.executable))
    result = subprocess.run([str(python), "-c", _STREAMRIP_EDIT, str(STREAMRIP_CONFIG), json.dumps(values)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Config de streamrip impossible : {result.stderr.strip()[-200:]}")
    try:
        STREAMRIP_CONFIG.chmod(0o600)  # contient les identifiants
    except OSError:
        pass
    return STREAMRIP_CONFIG


_TOOL_CODECS = {
    ".flac": ["-map", "0", "-c:a", "flac", "-c:v", "copy"],
    ".mp3": ["-map", "0", "-c:a", "libmp3lame", "-q:a", "0", "-c:v", "copy", "-id3v2_version", "3"],
    ".wav": ["-vn", "-c:a", "pcm_s16le"],
    ".aiff": ["-map", "0", "-c:a", "pcm_s16be", "-c:v", "copy", "-write_id3v2", "1", "-id3v2_version", "3"],
}


def _tool_convert(job_dir: Path, container: str) -> None:
    """Fichier de streamrip / Votify gardé tel quel en « original », sinon converti par ffmpeg
    (titre et pochette gardés si le format les accepte)."""
    src = _media_file(job_dir)
    target = f".{container}"
    if not src or container == "original" or src.suffix.lower() == target:
        return
    out = src.with_suffix(target)
    args = _TOOL_CODECS[target]
    run = lambda a: subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-y", "-i", str(src), *a, str(out)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    result = run(args)
    if result.returncode != 0 and "-vn" not in args:  # pochette refusée : le son sans pochette
        result = run(["-vn"] + [x for x in args if x not in ("-map", "0", "-c:v", "copy")])
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"La conversion a échoué : {result.stderr.strip()[-300:]}")
    src.unlink(missing_ok=True)


def _tool_command(service: str, url: str, work: Path, quality: int = 2) -> list:
    if service == "spotify":
        cookies = work / ".cookies.txt"  # le cookie sp_dc du compte, au format attendu par Votify
        _private_write(cookies, "# Netscape HTTP Cookie File\n.spotify.com\tTRUE\t/\tTRUE\t0\tsp_dc\t"
                       + _streamrip_creds().get("spotify_sp_dc", "") + "\n")
        return [_tool_bin("votify"), "--no-config-file", "-c", str(cookies), "-o", str(work),
                "--temp", str(work / ".tmp"), "--ffmpeg-path", FFMPEG, "--session-type", "librespot",
                "--audio-quality", "vorbis-high,vorbis-medium", "--no-synced-lyrics-file",
                "--log-level", "ERROR", url]
    config = _streamrip_write_config(work, quality)
    return [_tool_bin("rip"), "--config-path", str(config), "--no-db", "--no-progress", "url", url]


DEEZER_MP3_NOTE = "FLAC indisponible, MP3 320 à la place."
# Ce que streamrip écrit dans son journal quand Deezer refuse un morceau → message clair
_DEEZER_REASONS = [
    (r"AuthenticationError|MissingCredentials|invalid arl",
     "Deezer refuse ton ARL : il a sans doute expiré. Mets-en un nouveau dans les Réglages (Sources avec abonnement)."),
    (r"country|location|geolocation",
     "Ce morceau Deezer n'est pas disponible dans ton pays."),
    (r"Missing download info|not available for stream|NonStreamable",
     "Deezer ne propose pas ce morceau en téléchargement (retiré, ou réservé à certains pays)."),
]


def _run_source_tool(job: dict, cmd: list, work: Path, log_path: Path, started: float) -> tuple:
    """Lance streamrip ou Votify, attend la fin. Renvoie (fichiers audio produits, journal)."""
    with log_path.open("wb") as log:
        # Lignes longues : le journal de streamrip (rich) n'est pas coupé, les messages restent lisibles
        env = {**os.environ, "COLUMNS": "1000"}
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(work),
                                env=env, **({"creationflags": 0x08000000} if sys.platform.startswith("win") else {}))
        while proc.poll() is None:
            if job["_cancel"] or time.time() - started > TOOL_TIMEOUT:
                proc.kill()
                proc.wait()
                if job["_cancel"]:
                    raise JobCancelled()
                raise RuntimeError("Le téléchargement met trop de temps.")
            time.sleep(0.5)
    files = sorted((f for f in work.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS
                    and ".tmp" not in f.parts),
                   key=lambda f: f.stat().st_size, reverse=True)
    try:
        text = re.sub(r"\s+", " ", log_path.read_text("utf-8", errors="replace"))
    except OSError:
        text = ""
    return files, text


def _deezer_reason(log_text: str) -> str:
    for pattern, message in _DEEZER_REASONS:
        if re.search(pattern, log_text, re.IGNORECASE):
            return message
    return "Deezer n'a pas fourni ce morceau, ni en FLAC ni en MP3 320."


def _fetch_streamrip(job: dict, p: dict, url: str, job_dir: Path, index: int, count: int, service: str) -> dict:
    """Télécharge un morceau avec streamrip ou Votify. Lève une erreur si rien n'est produit
    (l'appelant retombe alors sur yt-dlp, sauf pour Deezer : yt-dlp n'y arrive jamais, DRM).
    Deezer : FLAC d'abord ; s'il est refusé (abonnement non HiFi), nouvel essai en MP3 320."""
    work = job_dir / ".source"
    log_path = job_dir / ".source.log"
    job.update(status="downloading", speed=None, eta=None)
    started = time.time()
    mp3_fallback = False
    try:
        for quality in ((2, 1) if service == "deezer" else (2,)):
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            files, log_text = _run_source_tool(job, _tool_command(service, url, work, quality), work, log_path, started)
            if files:
                break
            if service == "deezer" and quality == 2:
                if re.search(r"AuthenticationError|MissingCredentials", log_text):
                    break  # ARL refusé : inutile de réessayer en MP3
                continue
        if not files:
            if service == "deezer":
                raise RuntimeError(_deezer_reason(log_text))
            raise RuntimeError("Aucun fichier n'a été produit.")
        # MP3 : abonnement sans FLAC (2e essai), ou morceau sans version FLAC (streamrip choisit seul)
        mp3_fallback = service == "deezer" and files[0].suffix.lower() == ".mp3"
        final = job_dir / files[0].name
        shutil.move(str(files[0]), str(final))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        log_path.unlink(missing_ok=True)
    if mp3_fallback:
        job["note"] = DEEZER_MP3_NOTE
    info: dict = {"extractor_key": "Votify" if service == "spotify" else "streamrip", "title": final.stem}
    try:
        import mutagen
        tags = mutagen.File(final, easy=True)
        if tags is not None:
            info["duration"] = getattr(tags.info, "length", None)
            title = (tags.get("title") or [None])[0]
            artist = (tags.get("artist") or [None])[0]
            info["title"] = f"{artist} - {title}" if artist and title else title or final.stem
    except Exception:
        pass
    if count == 1 and job["title"] == url:
        job["title"] = info["title"]
    job["progress"] = round((index + 1) / count * 100, 1)
    # MP3 de secours gardé tel quel : le convertir en FLAC / WAV / AIFF grossirait le fichier sans
    # rien gagner en qualité
    keep_mp3 = mp3_fallback and p["container"] in ("flac", "wav", "aiff")
    if p["container"] != "original" and not keep_mp3:
        job.update(status="converting", speed=None, eta=None)
        _tool_convert(job_dir, p["container"])
    _auto_album(_media_file(job_dir), info.get("duration"))
    return info


def _fetch_media(job: dict, p: dict, url: str, job_dir: Path, index: int = 0, count: int = 1) -> dict:
    """Télécharge un média dans job_dir avec les options p. index/count : place dans un lot de liens."""
    service = _streamrip_service(url) if p["mode"] == "audio" else None
    if service:
        try:
            return _fetch_streamrip(job, p, url, job_dir, index, count, service)
        except JobCancelled:
            raise
        except Exception:
            if job["_cancel"]:
                raise JobCancelled()
            if service == "deezer":  # yt-dlp échoue toujours sur Deezer (DRM) : la vraie raison
                raise
            for leftover in job_dir.iterdir():  # reste d'un essai raté : yt-dlp repart à neuf
                if leftover.is_file() and leftover.suffix.lower() in AUDIO_EXTS:
                    leftover.unlink(missing_ok=True)
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
        ydl_opts["format"] = AUDIO_FORMAT
        postprocessors.insert(0, {
            "key": "FFmpegExtractAudio",
            # "best" garde le codec de la source : simple changement de conteneur, aucune perte
            # AIFF : WAV d'abord, converti juste après (_wav_to_aiff)
            "preferredcodec": "best" if container == "original" else "wav" if container == "aiff" else container,
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

    def run(ydl):
        ydl.add_post_processor(_FileTags(ydl, music=p["mode"] == "audio"), when="pre_process")
        if ydl_opts.get("writethumbnail") and not converted:
            ydl.add_post_processor(_CoverArt(ydl), when="post_process")
        return ydl.extract_info(url, download=True) or {}

    info = _run_ytdlp(ydl_opts, run, clean=job_dir)

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
    if p["mode"] == "audio" and container == "aiff":
        job.update(status="converting", speed=None, eta=None)
        _wav_to_aiff(job_dir)
    if p["mode"] == "audio":  # album, année d'origine… quand la recherche est sûre
        _auto_album(_media_file(job_dir), info.get("duration"))
    for leftover in job_dir.iterdir():  # pochettes non intégrées
        if leftover.suffix.lower() in IMAGE_EXTS:
            leftover.unlink(missing_ok=True)
    return info


def _download_sync(job: dict) -> None:
    p = job["_payload"]
    job_dir = ITEMS_DIR / job["id"]
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
            urls.append(await _expand_link(await _safe_url(raw)))
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=f"{raw} : {exc.detail}")
    if not urls:
        raise HTTPException(status_code=400, detail="Aucun lien.")
    n = len(urls)
    title = f"Plusieurs liens · {n} lien{'s' if n > 1 else ''}"
    data = {**payload.model_dump(), "urls": urls}
    job = _new_job("links", title, None, data)
    job.update(step=None, found=0, missing=0)
    job_dir = ITEMS_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {"status": "queued", "kind": "links", "title": title, "created": job["created"]})
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _links_sync(job: dict) -> None:
    """Télécharge chaque lien dans son sous-dossier, puis range tout dans un zip."""
    p = job["_payload"]
    job_dir = ITEMS_DIR / job["id"]
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
    src = _media_file(_item_dir(item_id))
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
    data = {**payload.model_dump(), "format": fmt, "src": str(src), "parent_id": item_id,
            "filename": f"{src.stem[:150]} (édité).{fmt}", **probe}
    job = _new_job("edit", title, item.get("thumbnail"), data)
    job_dir = ITEMS_DIR / job["id"]
    job_dir.mkdir(parents=True)
    _write_meta(job_dir, {"status": "queued", "kind": "edit", "parent": item_id, "title": title,
                          "created": job["created"]})
    await QUEUE.put(job["id"])
    return {"job_id": job["id"]}


def _edit_sync(job: dict) -> None:
    p = job["_payload"]
    job_dir = ITEMS_DIR / job["id"]
    out = job_dir / p["filename"]
    log_path = job_dir / ".ffmpeg.log"
    total = p["end"] - p["start"]
    job["status"] = "processing"

    _run_ffmpeg(job, _build_edit_cmd(p, Path(p["src"]), out), total, log_path, "Le montage a échoué")
    if not out.exists():
        raise RuntimeError("Le montage a échoué : aucun fichier produit.")

    job["filename"] = out.name
    parent = _read_meta(ITEMS_DIR / p["parent_id"])
    _write_meta(job_dir, {
        "status": "done",
        "kind": "edit",
        "parent": p["parent_id"],
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
    # Dossier temporaire plutôt que NamedTemporaryFile : sous Windows, un fichier temporaire encore
    # ouvert ne peut pas être lu par ffmpeg, et toute capture finissait en « Impossible de lire ».
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "capture.img"
        image.write_bytes(data)
        try:
            found = await asyncio.get_running_loop().run_in_executor(None, _ocr_lines, image)
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
    entries = [{"id": s["id"], "query": s["query"], "video_id": (s.get("pick") or {}).get("id")} for s in sons]
    return await queue_sons(entries, payload)


async def queue_sons(entries: list, payload: SonsFetchRequest) -> dict:
    """Lance la recherche de ces titres sur YouTube. Aussi utilisé par le téléphone (jumelage.py)."""
    n = len(entries)
    title = f"Liste de sons · {n} titre{'s' if n > 1 else ''}"
    data = {"sons": entries, **payload.model_dump()}
    job = _new_job("sons", title, None, data)
    job.update(step=None, found=0, missing=0)
    job_dir = ITEMS_DIR / job["id"]
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
    job_dir = ITEMS_DIR / job["id"]
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
            "format": AUDIO_FORMAT,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav" if p["container"] == "aiff" else p["container"],
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
                    def run(ydl, url=url):
                        ydl.add_post_processor(_FileTags(ydl, music=True), when="pre_process")
                        if opts.get("writethumbnail"):
                            ydl.add_post_processor(_CoverArt(ydl), when="post_process")
                        ydl.extract_info(url, download=True)

                    _run_ytdlp(opts, run, clean=target)
                    if p["container"] == "aiff":
                        _wav_to_aiff(target)
                    media = _media_file(target)
                    _auto_album(media, None)
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
