#!/usr/bin/env python3
"""Lance MediaVior sur ton ordinateur (version locale, sans serveur).

    python mediavior.py               démarre l'appli et ouvre sa fenêtre
    python mediavior.py --raccourci   crée le raccourci « MediaVior » sur le bureau
    python mediavior.py --verifier    vérifie l'installation (Python, ffmpeg, dossier) et quitte

Options : --port 8010, --dossier CHEMIN (dossier des téléchargements, retenu pour la suite),
--sans-fenetre (n'ouvre pas le navigateur, utilisé par Pinokio), --sans-maj (pas de mise à jour),
--demarrage (lancé au démarrage de l'ordinateur : en arrière-plan, sans fenêtre).

Les fichiers vont par défaut dans le dossier « MediaChest », à côté de l'appli installée
(Windows, Linux) ou dans Téléchargements (Mac, version Python). Les réglages et le journal
sont dans ~/.mediavior/.
"""
import argparse
import hashlib
import html
import importlib.abc
import importlib.machinery
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import re
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

# Appli « prête à installer » (.exe, .dmg, AppImage construits par GitHub, voir
# packaging/) : Python, yt-dlp, ffmpeg et deno sont dans le paquet, rangés dans sys._MEIPASS.
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = ROOT if FROZEN else ROOT / "app"
HOME_DIR = Path.home() / ".mediavior"
YTDLP_DIR = HOME_DIR / "yt-dlp"  # versions plus récentes de yt-dlp, téléchargées après coup
GITHUB_API = "https://api.github.com/repos/chr2l/MediaVior/releases/latest"
RELEASE_ASSETS = {"win": "MediaVior-Windows.exe", "mac": "MediaVior-Mac.dmg", "linux": "MediaVior-Linux.AppImage"}
CONFIG = HOME_DIR / "config.json"
LOG = HOME_DIR / "mediavior.log"
DEFAULT_PORT = 8010
UPDATE_EVERY = 24 * 3600
YTDLP_CHECK_EVERY = 6 * 3600  # appli installée : nouvelle version de yt-dlp ?
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def build_info() -> dict:
    """Version de l'appli et de yt-dlp inclus (fichier écrit par la construction GitHub)."""
    try:
        return json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _app_folder() -> Optional[Path]:
    """Dossier où se trouve l'appli installée : celui de MediaVior.exe (Windows) ou du fichier
    AppImage (Linux). None pour le Mac (appli dans Applications) et la version Python."""
    if not FROZEN or IS_MAC:
        return None
    exe = Path(os.environ.get("APPIMAGE") or sys.executable).resolve()
    return exe.parent


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".mediavior-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def default_folder() -> Path:
    """Dossier des médias, « MediaChest » :
    - Windows et Linux (AppImage) : à côté de l'appli, dans le même dossier qu'elle ;
    - Mac et version Python : dans Téléchargements.
    Les médias rangés avant dans Téléchargements/MediaChest (ou l'ancien Téléchargements/MediaVior)
    y sont déplacés une fois, au premier lancement."""
    downloads = Path.home() / "Downloads"
    olds = [downloads / "MediaChest", downloads / "MediaVior"]
    app = _app_folder()
    new = app / "MediaChest" if app and _writable(app) else olds[0]
    for old in olds:
        if old == new or not old.is_dir():
            continue
        if new.exists() and any(new.iterdir()):
            break  # le nouveau dossier sert déjà : on n'y touche plus
        try:
            if new.exists():
                new.rmdir()
            shutil.move(str(old), str(new))
        except OSError:
            return old  # déplacement impossible (fichier ouvert…) : on garde l'ancien dossier
        break
    return new


# ---------------------------------------------------------------------------
# Outils externes : ffmpeg, deno (YouTube), tesseract (captures)
# ---------------------------------------------------------------------------

def prepare_path() -> None:
    # Les outils installés par pip dans l'environnement (deno, ffmpeg de secours)
    # sont à côté de python : on les rend visibles pour yt-dlp et l'appli.
    bindir = str(Path(sys.executable).parent)
    os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
    if FROZEN:
        # ffmpeg, ffprobe et deno livrés dans le paquet ; certificats HTTPS de certifi (le Mac
        # n'en fournit pas à Python)
        os.environ["PATH"] = str(ROOT / "bin") + os.pathsep + os.environ["PATH"]
        try:
            import certifi
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            pass
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        try:
            import static_ffmpeg  # téléchargé au premier lancement si besoin
            static_ffmpeg.add_paths(weak=True)
        except Exception as exc:  # pas bloquant ici : --verifier le signale
            print(f"ffmpeg de secours indisponible : {exc}", file=sys.stderr)
    if IS_WIN and not shutil.which("tesseract"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "")):
            exe = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if base and exe.is_file():
                os.environ["PATH"] += os.pathsep + str(exe.parent)
                break


def check() -> int:
    prepare_path()
    ok = True
    print(f"Python {sys.version.split()[0]} : {'ok' if sys.version_info >= (3, 10) else 'trop ancien (3.10 minimum)'}")
    ok &= sys.version_info >= (3, 10)
    for mod in ("fastapi", "uvicorn", "yt_dlp", "jinja2"):
        try:
            __import__(mod)
            print(f"{mod} : ok")
        except ImportError:
            print(f"{mod} : MANQUANT (pip install -r requirements.txt -r requirements-local.txt)")
            ok = False
    for mod in ("segno", "aiortc"):
        try:
            __import__(mod)
            print(f"{mod} : ok")
        except ImportError:
            print(f"{mod} : absent (optionnel : téléphone relié)")
    if IS_WIN:
        # Fenêtre propre à MediaVior : pywebview, pythonnet et le moteur WebView2 d'Edge
        try:
            from webview.platforms.winforms import _is_chromium
            print(f"Fenêtre MediaVior : {'ok' if _is_chromium() else 'WebView2 absent (fenêtre Edge/Chrome à la place)'}")
        except Exception as exc:
            print(f"Fenêtre MediaVior : absente ({exc}) ; fenêtre Edge/Chrome à la place")
            ok &= not FROZEN  # l'appli installée doit l'avoir (vérifié à la construction)
    for tool, needed in (("ffmpeg", True), ("ffprobe", True), ("deno", True), ("tesseract", False)):
        found = shutil.which(tool)
        label = "ok" if found else ("MANQUANT" if needed else "absent (optionnel : lecture des captures)")
        print(f"{tool} : {label}")
        ok &= bool(found) or not needed
    folder = Path(load_config().get("folder") or default_folder())
    print(f"Dossier des téléchargements : {folder}")
    print("Tout est prêt." if ok else "Il manque quelque chose (voir ci-dessus).")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Mise à jour (au plus une fois par jour, en arrière-plan)
# ---------------------------------------------------------------------------

def update_in_background(cfg: dict) -> None:
    if FROZEN:
        threading.Thread(target=update_frozen, args=(cfg,), daemon=True).start()
        return
    if time.time() - cfg.get("last_update", 0) < UPDATE_EVERY:
        return

    def run():
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                 "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        pip = [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
        try:
            if (ROOT / ".git").is_dir() and shutil.which("git"):
                before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout
                subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=ROOT, timeout=120, **quiet)
                after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout
                if before != after:
                    subprocess.run(pip + ["-r", "requirements.txt", "-r", "requirements-local.txt"],
                                   cwd=ROOT, timeout=600, **quiet)
            # Les sites changent souvent : yt-dlp doit rester à jour
            subprocess.run(pip + ["-U", "yt-dlp[default]"], timeout=300, **quiet)
            cfg["last_update"] = time.time()
            save_config(cfg)
        except Exception as exc:
            print(f"Mise à jour impossible : {exc}", file=sys.stderr)

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Mise à jour de l'appli prête à installer (.exe, .dmg, AppImage)
# ---------------------------------------------------------------------------
# On ne peut pas faire « pip install » dans un paquet figé. Donc :
#   - yt-dlp : la dernière version est téléchargée depuis PyPI (fichier .whl, vérifié par son
#     empreinte SHA-256) dans ~/.mediavior/yt-dlp, et utilisée à la place de celle du paquet ;
#   - l'appli : si une nouvelle version est publiée sur GitHub, un bouton « Mettre à jour »
#     apparaît (Windows et Linux l'installent seuls, le Mac télécharge le .dmg).

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def _get_json(url: str):
    req = Request(url, headers={"User-Agent": "MediaVior", "Accept": "application/json"})
    with urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _download(url: str, dest: Path, sha256: Optional[str] = None, progress=None) -> None:
    """Télécharge url dans dest. progress(pourcentage) est appelé au fil du téléchargement."""
    tmp = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    with urlopen(Request(url, headers={"User-Agent": "MediaVior"}), timeout=60) as resp, tmp.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 16):
            digest.update(chunk)
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(100, done * 100 // total))
    if sha256 and digest.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"empreinte incorrecte pour {dest.name}")
    tmp.replace(dest)


def _pypi_wheel(project: str, version: Optional[str] = None) -> tuple:
    data = _get_json(f"https://pypi.org/pypi/{project}/{version + '/' if version else ''}json")
    for f in data["urls"]:
        if f["packagetype"] == "bdist_wheel" and f["filename"].endswith("-py3-none-any.whl"):
            return data["info"]["version"], data["info"].get("requires_dist") or [], f
    raise ValueError(f"pas de wheel pour {project}")


def update_ytdlp_wheel() -> None:
    YTDLP_DIR.mkdir(parents=True, exist_ok=True)
    current = _ytdlp_override() or {}
    bundled = build_info().get("yt_dlp", "0")
    version, requires, wheel = _pypi_wheel("yt-dlp")
    best = max(_version_tuple(bundled), _version_tuple(current.get("version", "0")))
    if _version_tuple(version) <= best:
        return
    new = {"version": version}
    dest = YTDLP_DIR / wheel["filename"]
    _download(wheel["url"], dest, wheel["digests"]["sha256"])
    new["yt_dlp"] = dest.name
    # yt-dlp-ejs (défis JavaScript de YouTube) va avec une version précise de yt-dlp
    ejs = next((re.search(r"==\s*([\w.]+)", r) for r in requires if r.startswith("yt-dlp-ejs")), None)
    if ejs:
        _, _, ejs_wheel = _pypi_wheel("yt-dlp-ejs", ejs.group(1))
        ejs_dest = YTDLP_DIR / ejs_wheel["filename"]
        _download(ejs_wheel["url"], ejs_dest, ejs_wheel["digests"]["sha256"])
        new["yt_dlp_ejs"] = ejs_dest.name
    (YTDLP_DIR / "actuel.json").write_text(json.dumps(new), encoding="utf-8")
    # Ménage : on garde seulement les fichiers utilisés
    keep = {new.get("yt_dlp"), new.get("yt_dlp_ejs"), "actuel.json"}
    for f in YTDLP_DIR.iterdir():
        if f.name not in keep:
            f.unlink(missing_ok=True)
    print(f"yt-dlp {version} téléchargé : utilisé au prochain lancement.")


def _ytdlp_override() -> Optional[dict]:
    try:
        cur = json.loads((YTDLP_DIR / "actuel.json").read_text(encoding="utf-8"))
        return cur if (YTDLP_DIR / cur["yt_dlp"]).is_file() else None
    except (OSError, ValueError, KeyError):
        return None


class _WheelFinder(importlib.abc.MetaPathFinder):
    """Importe yt_dlp (et yt_dlp_ejs) depuis le .whl téléchargé plutôt que depuis le paquet."""

    def __init__(self, wheels: dict):
        self.wheels = wheels

    def find_spec(self, fullname, path, target=None):
        top = fullname.partition(".")[0]
        if top not in self.wheels:
            return None
        search = [self.wheels[top]] if "." not in fullname else path
        return importlib.machinery.PathFinder.find_spec(fullname, search)


def use_newer_ytdlp() -> None:
    cur = _ytdlp_override()
    if not cur or _version_tuple(cur.get("version")) <= _version_tuple(build_info().get("yt_dlp", "0")):
        return
    wheels = {"yt_dlp": str(YTDLP_DIR / cur["yt_dlp"])}
    if cur.get("yt_dlp_ejs") and (YTDLP_DIR / cur["yt_dlp_ejs"]).is_file():
        wheels["yt_dlp_ejs"] = str(YTDLP_DIR / cur["yt_dlp_ejs"])
    sys.meta_path.insert(0, _WheelFinder(wheels))


def _platform_key() -> str:
    return "win" if IS_WIN else "mac" if IS_MAC else "linux"


def check_app_release() -> Optional[dict]:
    current = build_info().get("version")
    if not current:
        return None
    rel = _get_json(GITHUB_API)
    tag = rel.get("tag_name", "")
    if _version_tuple(tag) <= _version_tuple(current):
        return None
    name = RELEASE_ASSETS[_platform_key()]
    asset = next((a for a in rel.get("assets", []) if a.get("name") == name), None)
    if not asset:
        return None
    return {"version": tag.lstrip("v"), "url": asset["browser_download_url"], "page": rel.get("html_url"),
            "auto": not IS_MAC}


def install_app_update(info: dict, quit_hook) -> None:
    """Windows : lance l'installeur sans fenêtre puis quitte (il relance l'appli).
    Linux : remplace le fichier AppImage, puis relance. Mac : ouvre la page de téléchargement.
    La progression va dans STATE["install"] : la page de l'appli l'affiche elle-même."""
    if IS_MAC:
        webbrowser.open(info["url"])
        return

    def step(phase: str, percent: int = 0) -> None:
        STATE["install"] = {"phase": phase, "percent": percent, "version": info["version"]}

    step("download")
    tmpdir = Path(tempfile.mkdtemp(prefix="mediavior-maj-"))
    if IS_WIN:
        setup = tmpdir / RELEASE_ASSETS["win"]
        _download(info["url"], setup, progress=lambda pc: step("download", pc))
        step("install", 100)
        time.sleep(1.5)  # la page a le temps de voir « Installation… » avant l'arrêt
        # /VERYSILENT : aucune fenêtre d'installeur, la page de l'appli montre l'avancement.
        # /APRESMAJ=1 : l'installeur relance MediaVior sans rouvrir de fenêtre (la page se recharge).
        subprocess.Popen([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/APRESMAJ=1"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        quit_hook()
        return
    appimage = os.environ.get("APPIMAGE")
    if not appimage:
        STATE["install"] = None
        webbrowser.open(info["url"])
        return
    new = Path(appimage).with_name(Path(appimage).name + ".nouveau")
    _download(info["url"], new, progress=lambda pc: step("download", pc))
    step("install", 100)
    new.chmod(0o755)
    new.replace(appimage)
    time.sleep(1.5)
    subprocess.Popen([appimage, "--apres-maj"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    quit_hook()


def start_app_update(info: dict, quit_hook) -> None:
    """Démarre la mise à jour en arrière-plan (la page suit l'avancement)."""
    if (STATE.get("install") or {}).get("phase") in ("download", "install"):
        return  # déjà en cours
    if IS_MAC:
        install_app_update(info, quit_hook)
        return

    def run():
        try:
            install_app_update(info, quit_hook)
        except Exception as exc:
            print(f"Mise à jour impossible : {exc}", file=sys.stderr)
            STATE["install"] = {"phase": "error", "error": str(exc), "version": info["version"]}

    STATE["install"] = {"phase": "download", "percent": 0, "version": info["version"]}
    threading.Thread(target=run, daemon=True).start()


def update_frozen(cfg: dict) -> None:
    try:  # nouvelle version de l'appli : vérifiée à chaque lancement (une petite requête)
        STATE["release"] = check_app_release()
    except Exception as exc:
        print(f"Vérification de la version impossible : {exc}", file=sys.stderr)
    # yt-dlp : vérifié à chaque lancement puis toutes les 6 h (l'appli peut rester ouverte des
    # jours si elle démarre avec l'ordinateur). Une version trop ancienne donne des erreurs 403.
    while True:
        try:
            update_ytdlp_wheel()
            cfg["last_update"] = time.time()
            save_config(cfg)
        except Exception as exc:
            print(f"Mise à jour de yt-dlp impossible : {exc}", file=sys.stderr)
        time.sleep(YTDLP_CHECK_EVERY)


STATE: dict = {"release": None, "install": None}


# ---------------------------------------------------------------------------
# Fenêtre
# ---------------------------------------------------------------------------

def is_mediavior(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as resp:
            return json.load(resp).get("app") == "mediavior"
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def chromium_browsers() -> list:
    """Navigateurs qui savent ouvrir une fenêtre d'appli : (programme, dossier de leurs profils)."""
    found = []
    if IS_WIN:
        local = os.environ.get("LOCALAPPDATA", "")
        profiles = {"msedge.exe": Path(local) / "Microsoft/Edge/User Data",
                    "chrome.exe": Path(local) / "Google/Chrome/User Data",
                    "brave.exe": Path(local) / "BraveSoftware/Brave-Browser/User Data"}
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), local):
            if base:
                for exe in (Path(base) / "Microsoft/Edge/Application/msedge.exe",
                            Path(base) / "Google/Chrome/Application/chrome.exe",
                            Path(base) / "BraveSoftware/Brave-Browser/Application/brave.exe"):
                    found.append((exe, profiles[exe.name]))
    elif IS_MAC:
        sup = Path.home() / "Library/Application Support"
        found += [(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), sup / "Google/Chrome"),
                  (Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), sup / "Microsoft Edge"),
                  (Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                   sup / "BraveSoftware/Brave-Browser")]
    else:
        conf = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        for name, prof in (("google-chrome", "google-chrome"), ("chromium", "chromium"),
                           ("chromium-browser", "chromium"), ("microsoft-edge", "microsoft-edge"),
                           ("brave-browser", "BraveSoftware/Brave-Browser")):
            if shutil.which(name):
                found.append((Path(shutil.which(name)), conf / prof))
    return [(exe, prof) for exe, prof in found if exe.is_file()]


def web_app_id(url: str) -> str:
    """Identifiant que Chrome et Edge donnent à MediaVior installé comme appli : calculé à partir
    de l'« id » du manifeste ("/", donc l'adresse de l'appli), comme le fait Chromium
    (deux passages de SHA-256, puis les 32 premiers chiffres écrits avec les lettres a à p)."""
    digest = hashlib.sha256(hashlib.sha256(url.encode()).digest()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def installed_window(url: str) -> Optional[list]:
    """Commande qui ouvre MediaVior installé comme appli dans Edge/Chrome (barre du haut aux
    couleurs de l'appli), ou None s'il n'est installé dans aucun navigateur."""
    app_id = web_app_id(url)
    for exe, user_data in chromium_browsers():
        try:
            profiles = sorted(p for p in user_data.iterdir() if (p / "Web Applications").is_dir())
        except OSError:
            continue
        for prof in profiles:
            if (prof / "Web Applications" / "Manifest Resources" / app_id).is_dir():
                return [str(exe), f"--profile-directory={prof.name}", f"--app-id={app_id}"]
    return None


def open_in_browser_tab(url: str) -> bool:
    """Ouvre un onglet ordinaire d'Edge/Chrome (là où le bouton « Installer » existe)."""
    for exe, _ in chromium_browsers():
        try:
            subprocess.Popen([str(exe), url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


def native_window_available() -> bool:
    """Windows : la fenêtre à MediaVior (pywebview + WebView2, déjà présent sur Windows 10/11)."""
    if not IS_WIN:
        return False
    import importlib.util
    return importlib.util.find_spec("webview") is not None


def _windows_light_theme() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return False


_KEEP = []  # fonctions appelées par Windows : gardées en vie tant que la fenêtre existe


def _remove_windows_title_bar(hwnd: int) -> None:
    """Enlève la barre de titre de Windows mais garde le reste du cadre : bords pour
    redimensionner, ombre, coins arrondis, agrandir en glissant vers le haut de l'écran.
    La page dessine sa propre barre à la place (index.html, .titlebar).
    Principe : au calcul du cadre (WM_NCCALCSIZE), on laisse Windows faire puis on remet le haut
    de la zone de la page tout en haut de la fenêtre. À appeler sur le fil de la fenêtre."""
    import ctypes
    from ctypes import wintypes
    user32, comctl32 = ctypes.windll.user32, ctypes.windll.comctl32
    LRESULT = ctypes.c_ssize_t
    SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.DefSubclassProc.restype = LRESULT
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    def frame_height(hwnd_):
        # Épaisseur du cadre caché : quand la fenêtre est agrandie, Windows la fait déborder de
        # l'écran d'autant ; on décale alors la page pour que sa barre reste visible.
        try:
            dpi = user32.GetDpiForWindow(hwnd_)
            return user32.GetSystemMetricsForDpi(33, dpi) + user32.GetSystemMetricsForDpi(92, dpi)
        except Exception:
            return user32.GetSystemMetrics(33) + user32.GetSystemMetrics(92)

    def proc(hwnd_, msg, wparam, lparam, _uid, _ref):
        if msg == 0x0083 and wparam:  # WM_NCCALCSIZE
            params = ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
            top = params.rgrc[0].top
            result = comctl32.DefSubclassProc(hwnd_, msg, wparam, lparam)
            params.rgrc[0].top = top + (frame_height(hwnd_) if user32.IsZoomed(hwnd_) else 0)
            return result
        return comctl32.DefSubclassProc(hwnd_, msg, wparam, lparam)

    callback = SUBCLASSPROC(proc)
    _KEEP.append(callback)
    if not comctl32.SetWindowSubclass(wintypes.HWND(hwnd), callback, 1, 0):
        raise OSError("SetWindowSubclass a échoué")
    # Fait recalculer le cadre tout de suite (SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER | NOACTIVATE)
    user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, 0x20 | 0x2 | 0x1 | 0x4 | 0x10)


def native_window(url: str) -> bool:
    """Windows : ouvre l'appli dans sa propre fenêtre (pas celle d'un navigateur), comme Discord
    ou Claude : la barre du haut est dessinée par la page (coffre bleu, nom, boutons réduire /
    agrandir / fermer), et Windows garde le redimensionnement par les bords et le glisser.
    Si la barre de Windows ne peut pas être enlevée, elle reste, aux couleurs de l'appli.
    Tourne dans un processus à part (MediaVior.exe --fenetre) qui s'arrête à la fermeture.
    Renvoie False si c'est impossible ici (pywebview ou WebView2 absent)."""
    try:
        import webview
        from webview.platforms.winforms import _is_chromium
        if not _is_chromium():  # sans WebView2, pywebview prendrait le vieux moteur d'Internet Explorer
            return False
    except Exception as exc:
        print(f"Fenêtre MediaVior indisponible : {exc}", file=sys.stderr)
        return False
    import ctypes
    light = _windows_light_theme()
    # Mêmes couleurs que style.css : fond (--ink) et texte (--paper), en clair ou en sombre
    bg, fg = ("#F3F5F8", "#17202B") if light else ("#121821", "#E9ECF1")
    colorref = lambda hexa: int(hexa[5:7] + hexa[3:5] + hexa[1:3], 16)  # Windows : 0x00BBGGRR
    state = {"bar": False, "native_drag": False, "ready": False, "hwnd": 0}

    def hwnd() -> int:
        return state["hwnd"]  # lu une fois sur le fil de la fenêtre (prepare)

    def maximized() -> bool:
        return bool(ctypes.windll.user32.IsZoomed(hwnd()))

    class Api:
        """Appelé par la page (local.js, « Barre du haut dessinée par la page »)."""
        def fenetre(self):
            return {"barre": state["bar"], "glisser_natif": state["native_drag"], "agrandie": maximized()}

        def reduire(self):
            window.minimize()

        def agrandir(self):
            if maximized():
                window.restore()
            else:
                window.maximize()
            return maximized()

        def agrandie(self):
            return maximized()

        def fermer(self):  # bouton de la barre, ou « Quitter MediaVior »
            window.destroy()

    # D'abord une page vide de la couleur du fond : la barre est préparée, puis l'appli s'affiche
    window = webview.create_window("MediaVior", html=f"<body style='background:{bg}'></body>",
                                   width=1200, height=820, min_size=(420, 560),
                                   background_color=bg, text_select=True, js_api=Api())

    def paint_title_bar():
        # Couleurs du cadre : barre de Windows (si elle reste) et fin liseré autour de la fenêtre
        try:
            for attr, value in ((20, 0 if light else 1), (35, colorref(bg)), (36, colorref(fg)),
                                (34, colorref(bg))):
                val = ctypes.c_int(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd()), attr,
                                                           ctypes.byref(val), ctypes.sizeof(val))
        except Exception as exc:
            print(f"Couleur de la barre : {exc}", file=sys.stderr)

    def prepare():
        # Sur le fil de la fenêtre (Windows et WebView2 l'exigent)
        state["hwnd"] = window.native.Handle.ToInt32()
        paint_title_bar()
        try:
            # La zone « app-region: drag » de la page se comporte comme une barre de titre :
            # glisser, coller au bord de l'écran, double-clic pour agrandir, clic droit
            window.native.browser.webview.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
            state["native_drag"] = True
        except Exception as exc:
            print(f"Glisser la barre (WebView2) : {exc}", file=sys.stderr)
        try:
            _remove_windows_title_bar(hwnd())
            state["bar"] = True
        except Exception as exc:
            print(f"Barre de la page : {exc}", file=sys.stderr)

    def on_loaded():
        if state["ready"]:
            return
        state["ready"] = True
        try:
            from System import Action
            window.native.Invoke(Action(prepare))
        except Exception as exc:
            print(f"Préparation de la fenêtre : {exc}", file=sys.stderr)
        window.load_url(url)

    window.events.loaded += on_loaded
    webview.settings["ALLOW_DOWNLOADS"] = True  # « Télécharger » depuis la bibliothèque
    storage = HOME_DIR / "fenetre"  # garde la langue choisie, etc. d'une ouverture à l'autre
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage))
    return True


def open_window(url: str) -> None:
    """Ouvre l'appli : sous Windows dans sa propre fenêtre (processus à part), sinon dans une
    fenêtre Edge/Chrome sans barre d'adresse, sinon un onglet."""
    if native_window_available():
        if FROZEN:
            cmd = [sys.executable, "--fenetre", url]
        else:
            py = Path(sys.executable)
            if py.with_name("pythonw.exe").is_file():
                py = py.with_name("pythonw.exe")  # pas de fenêtre noire
            cmd = [str(py), str(Path(__file__).resolve()), "--fenetre", url]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
        except OSError:
            pass
    browser_window(url)


def browser_window(url: str) -> None:
    """Fenêtre Edge/Chrome sans barre d'adresse, sinon un onglet. Si MediaVior est installé
    comme appli du navigateur, c'est cette fenêtre-là qui s'ouvre."""
    cmds = []
    try:
        installed = installed_window(url)
        if installed:
            cmds.append(installed)
    except Exception:
        pass
    cmds += [[str(exe), f"--app={url}", "--window-size=1200,820"] for exe, _ in chromium_browsers()]
    for cmd in cmds:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Lancement au démarrage de l'ordinateur (en arrière-plan, sans fenêtre)
# ---------------------------------------------------------------------------

AUTOSTART_NAME = "MediaVior"
MAC_AGENT = Path.home() / "Library" / "LaunchAgents" / "io.github.chr2l.mediavior.plist"
LINUX_AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "mediavior.desktop"


def _launch_command() -> list:
    """Commande qui lance MediaVior au démarrage, sans ouvrir de fenêtre."""
    if FROZEN:
        return [str(Path(os.environ.get("APPIMAGE") or sys.executable)), "--demarrage"]
    py = Path(sys.executable)
    if IS_WIN and py.with_name("pythonw.exe").is_file():
        py = py.with_name("pythonw.exe")  # pas de fenêtre noire
    return [str(py), str(ROOT / "mediavior.py"), "--demarrage"]


def autostart(enable: Optional[bool] = None) -> bool:
    """Sans argument : MediaVior se lance-t-il au démarrage ? Avec True/False : active ou coupe."""
    cmd = _launch_command()
    if IS_WIN:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            if enable is True:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(cmd))
            elif enable is False:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
            try:
                winreg.QueryValueEx(key, AUTOSTART_NAME)
                return True
            except FileNotFoundError:
                return False
    target = MAC_AGENT if IS_MAC else LINUX_AUTOSTART
    if enable is True:
        target.parent.mkdir(parents=True, exist_ok=True)
        if IS_MAC:
            args = "".join(f"<string>{html.escape(a)}</string>" for a in cmd)
            target.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.github.chr2l.mediavior</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""", encoding="utf-8")
        else:
            exec_line = " ".join(f'"{a}"' for a in cmd)
            target.write_text(f"""[Desktop Entry]
Type=Application
Name=MediaVior
Comment=Sauvegarde tes médias (lancement au démarrage)
Exec={exec_line}
X-GNOME-Autostart-enabled=true
NoDisplay=true
""", encoding="utf-8")
    elif enable is False:
        target.unlink(missing_ok=True)
    return target.is_file()


# ---------------------------------------------------------------------------
# Raccourci sur le bureau
# ---------------------------------------------------------------------------

def desktop_dir() -> Path:
    if IS_WIN:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True,
        ).stdout.strip()
        return Path(out) if out else Path.home() / "Desktop"
    if not IS_MAC and shutil.which("xdg-user-dir"):
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out:
            return Path(out)
    return Path.home() / "Desktop"


def create_shortcut() -> int:
    script = ROOT / "mediavior.py"
    icons = APP_DIR / "static" / "icons"
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)

    if FROZEN and IS_MAC:
        print("Sur Mac, glisse MediaVior dans le dossier Applications : il apparaît dans le Launchpad.")
        return 0
    # Appli prête à installer : on lance l'exécutable lui-même (ou le fichier AppImage)
    launch_args = "" if FROZEN else f'"{script}"'
    exe = Path(os.environ.get("APPIMAGE") or sys.executable)

    if IS_WIN:
        # pythonw : pas de fenêtre noire de console
        pyw = Path(sys.executable).with_name("pythonw.exe")
        target = exe if FROZEN else pyw if pyw.is_file() else Path(sys.executable)
        q = lambda v: str(v).replace("'", "''")  # échappement PowerShell
        ps = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @('{q(desk)}', [Environment]::GetFolderPath('Programs'))) {{
  $s = $ws.CreateShortcut((Join-Path $dir 'MediaVior.lnk'))
  $s.TargetPath = '{q(target)}'
  $s.Arguments = '{q(launch_args)}'
  $s.WorkingDirectory = '{q(target.parent if FROZEN else ROOT)}'
  $s.IconLocation = '{q(icons / "mediavior.ico")}'
  $s.Description = 'MediaVior : sauvegarde tes médias'
  $s.Save()
}}"""
        res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])
        where = desk / "MediaVior.lnk"
        if res.returncode != 0:
            return res.returncode

    elif IS_MAC:
        app = Path.home() / "Applications" / "MediaVior.app"
        macos = app / "Contents" / "MacOS"
        res_dir = app / "Contents" / "Resources"
        macos.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)
        launcher = macos / "MediaVior"
        launcher.write_text(f'#!/bin/sh\ncd "{ROOT}"\nexec "{sys.executable}" "{script}"\n', encoding="utf-8")
        launcher.chmod(0o755)
        (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>MediaVior</string>
  <key>CFBundleDisplayName</key><string>MediaVior</string>
  <key>CFBundleIdentifier</key><string>io.github.chr2l.mediavior</string>
  <key>CFBundleExecutable</key><string>MediaVior</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
</dict></plist>
""", encoding="utf-8")
        _mac_icon(icons / "icon-512.png", res_dir / "icon.icns")
        where = desk / "MediaVior.app"
        if where.is_symlink() or where.exists():
            where.unlink()
        where.symlink_to(app)

    else:
        icon_file = icons / "icon-512.png"
        if FROZEN:  # le dossier du paquet AppImage disparaît à la fermeture : on copie l'icône
            HOME_DIR.mkdir(parents=True, exist_ok=True)
            icon_file = HOME_DIR / "mediavior.png"
            shutil.copyfile(icons / "icon-512.png", icon_file)
        entry = f"""[Desktop Entry]
Type=Application
Name=MediaVior
Comment=Sauvegarde tes médias
Exec="{exe}" {launch_args}
Path={exe.parent if FROZEN else ROOT}
Icon={icon_file}
Terminal=false
Categories=AudioVideo;Network;
"""
        apps = Path.home() / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        for where in (apps / "mediavior.desktop", desk / "mediavior.desktop"):
            where.write_text(entry, encoding="utf-8")
            where.chmod(0o755)
        if shutil.which("gio"):
            subprocess.run(["gio", "set", str(where), "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"Raccourci créé : {where}")
    return 0


def _mac_icon(png: Path, icns: Path) -> None:
    """Fabrique l'icône .icns avec les outils de macOS (sips, iconutil). Facultatif."""
    try:
        iconset = icns.with_suffix(".iconset")
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                if px > 512:
                    continue
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(png), "--out", str(iconset / name)],
                               capture_output=True, check=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], capture_output=True, check=True)
        shutil.rmtree(iconset, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Démarrage
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Lance MediaVior sur ce PC.")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--dossier", help="dossier des téléchargements (retenu pour les prochaines fois)")
    parser.add_argument("--sans-fenetre", action="store_true", help="ne pas ouvrir le navigateur")
    parser.add_argument("--demarrage", action="store_true",
                        help="lancé au démarrage de l'ordinateur (sans fenêtre)")
    parser.add_argument("--sans-maj", action="store_true", help="ne pas chercher de mise à jour")
    parser.add_argument("--apres-maj", action="store_true", help=argparse.SUPPRESS)  # relancé par la mise à jour
    parser.add_argument("--raccourci", action="store_true", help="créer le raccourci sur le bureau")
    parser.add_argument("--verifier", action="store_true", help="vérifier l'installation")
    parser.add_argument("--fenetre", metavar="URL", help=argparse.SUPPRESS)  # fenêtre Windows (open_window)
    args = parser.parse_args()

    # Lancé sans console (raccourci Windows) : la sortie va dans le journal
    if sys.stdout is None or sys.stderr is None:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    if args.verifier:
        return check()
    if args.raccourci:
        return create_shortcut()
    if args.fenetre:
        if not native_window(args.fenetre):
            browser_window(args.fenetre)
        return 0

    cfg = load_config()
    if args.dossier:
        cfg["folder"] = str(Path(args.dossier).expanduser().resolve())
        save_config(cfg)
    folder = Path(cfg.get("folder") or default_folder())
    folder.mkdir(parents=True, exist_ok=True)

    port = args.port or cfg.get("port") or DEFAULT_PORT
    # Déjà ouvert ? On montre simplement la fenêtre.
    if is_mediavior(port):
        if not (args.sans_fenetre or args.demarrage or args.apres_maj):
            open_window(f"http://127.0.0.1:{port}/")
        print(f"MediaVior tourne déjà : http://127.0.0.1:{port}/")
        return 0
    while not port_free(port):
        port += 1

    prepare_path()
    if FROZEN and not IS_WIN and not IS_MAC and not cfg.get("raccourci"):
        # AppImage : au premier lancement, ajoute MediaVior au menu des applis et au bureau
        try:
            create_shortcut()
            cfg["raccourci"] = True
            save_config(cfg)
        except Exception as exc:
            print(f"Raccourci impossible : {exc}", file=sys.stderr)
    os.environ["MEDIAVIOR_LOCAL"] = "1"
    os.environ["LECOFFRE_DOWNLOAD_DIR"] = str(folder)
    # Dossiers à part pour les sons et les vidéos (Réglages), et historique des stats du coffre
    for kind in ("audio", "video"):
        if cfg.get(f"{kind}_folder"):
            os.environ[f"LECOFFRE_{kind.upper()}_DIR"] = cfg[f"{kind}_folder"]
    os.environ["MEDIAVIOR_STATE_DIR"] = str(HOME_DIR)
    os.environ["LECOFFRE_AUTO_UPDATE"] = "0"  # en local, c'est ce lanceur qui met à jour
    if not args.sans_maj:
        update_in_background(cfg)

    if FROZEN:
        use_newer_ytdlp()
    sys.path.insert(0, str(APP_DIR))
    import uvicorn
    import main as web  # app/main.py

    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="warning"))
    web.QUIT_HOOK = lambda: setattr(server, "should_exit", True)
    web.APP_VERSION = build_info().get("version") if FROZEN else None

    def remember_folder(path: str) -> None:
        cfg["folder"] = path
        save_config(cfg)

    web.FOLDER_HOOK = remember_folder

    def remember_kind_folder(kind: str, path: Optional[str]) -> None:
        if path:
            cfg[f"{kind}_folder"] = path
        else:
            cfg.pop(f"{kind}_folder", None)
        save_config(cfg)

    web.KIND_FOLDER_HOOK = remember_kind_folder

    def window_hook(open_tab: Optional[str] = None):
        """Fenêtre installée : WINDOW_HOOK() dit si elle l'est, WINDOW_HOOK("/chemin") ouvre un onglet."""
        if open_tab:
            return open_in_browser_tab(f"http://127.0.0.1:{port}{open_tab}")
        # Sous Windows, la fenêtre à MediaVior a déjà la barre aux couleurs : rien à installer
        return {"installed": native_window_available()
                or installed_window(f"http://127.0.0.1:{port}/") is not None,
                "browser": bool(chromium_browsers())}

    web.WINDOW_HOOK = window_hook
    if not args.sans_fenetre or args.demarrage:  # Pinokio (--sans-fenetre) gère seul le lancement
        web.AUTOSTART_HOOK = autostart
        try:
            if autostart():
                autostart(True)  # l'appli a pu changer de dossier (mise à jour) : chemin rafraîchi
        except Exception as exc:
            print(f"Lancement au démarrage : {exc}", file=sys.stderr)
    if FROZEN:
        web.APP_UPDATE = STATE  # « release » est rempli en arrière-plan s'il y a du nouveau
        web.APP_UPDATE_HOOK = lambda: start_app_update(STATE["release"], web.QUIT_HOOK)
        web.APP_UPDATE_CHECK = lambda: STATE.update(release=check_app_release())
    url = f"http://127.0.0.1:{port}/"

    def when_ready():
        for _ in range(100):
            if server.started:
                print(f"MediaVior est prêt : {url}", flush=True)
                if args.apres_maj:
                    # Après une mise à jour, l'ancienne fenêtre se recharge seule. Si elle a été
                    # fermée entre-temps (aucune visite en 20 s), on en rouvre une.
                    for _ in range(200):
                        if web.PAGE_SEEN:
                            return
                        time.sleep(0.1)
                    open_window(url)
                elif not (args.sans_fenetre or args.demarrage):
                    open_window(url)
                return
            time.sleep(0.1)

    threading.Thread(target=when_ready, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
