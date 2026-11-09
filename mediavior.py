#!/usr/bin/env python3
"""Lance MediaVior sur ton ordinateur (version locale, sans serveur).

    python mediavior.py               démarre l'appli et ouvre sa fenêtre
    python mediavior.py --raccourci   crée le raccourci « MediaVior » sur le bureau
    python mediavior.py --verifier    vérifie l'installation (Python, ffmpeg, dossier) et quitte

Options : --port 8010, --dossier CHEMIN (dossier des téléchargements, retenu pour la suite),
--sans-fenetre (n'ouvre pas le navigateur, utilisé par Pinokio), --sans-maj (pas de mise à jour).

Les fichiers vont par défaut dans « Téléchargements/MediaVior ». Les réglages et le journal
sont dans ~/.mediavior/.
"""
import argparse
import hashlib
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


def default_folder() -> Path:
    return Path.home() / "Downloads" / "MediaVior"


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


def _download(url: str, dest: Path, sha256: Optional[str] = None) -> None:
    tmp = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    with urlopen(Request(url, headers={"User-Agent": "MediaVior"}), timeout=60) as resp, tmp.open("wb") as f:
        while chunk := resp.read(1 << 16):
            digest.update(chunk)
            f.write(chunk)
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
    """Windows : lance l'installeur en silencieux puis quitte (il relance l'appli).
    Linux : remplace le fichier AppImage, puis relance. Mac : ouvre la page de téléchargement."""
    if IS_MAC:
        webbrowser.open(info["url"])
        return
    tmpdir = Path(tempfile.mkdtemp(prefix="mediavior-maj-"))
    if IS_WIN:
        setup = tmpdir / RELEASE_ASSETS["win"]
        _download(info["url"], setup)
        subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        quit_hook()
        return
    appimage = os.environ.get("APPIMAGE")
    if not appimage:
        webbrowser.open(info["url"])
        return
    new = Path(appimage).with_name(Path(appimage).name + ".nouveau")
    _download(info["url"], new)
    new.chmod(0o755)
    new.replace(appimage)
    subprocess.Popen([appimage], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    quit_hook()


def update_frozen(cfg: dict) -> None:
    try:  # nouvelle version de l'appli : vérifiée à chaque lancement (une petite requête)
        STATE["release"] = check_app_release()
    except Exception as exc:
        print(f"Vérification de la version impossible : {exc}", file=sys.stderr)
    if time.time() - cfg.get("last_update", 0) < UPDATE_EVERY:
        return
    try:
        update_ytdlp_wheel()
        cfg["last_update"] = time.time()
        save_config(cfg)
    except Exception as exc:
        print(f"Mise à jour de yt-dlp impossible : {exc}", file=sys.stderr)


STATE: dict = {"release": None}


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


def open_window(url: str) -> None:
    """Ouvre l'appli dans une fenêtre sans barre d'adresse (Edge/Chrome), sinon un onglet."""
    candidates = []
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe",
                               Path(base) / "BraveSoftware/Brave-Browser/Application/brave.exe"]
    elif IS_MAC:
        candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                       Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")]
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            if shutil.which(name):
                candidates.append(Path(shutil.which(name)))
    for exe in candidates:
        if exe.is_file():
            try:
                subprocess.Popen([str(exe), f"--app={url}", "--window-size=1200,820"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    webbrowser.open(url)


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
    parser.add_argument("--sans-maj", action="store_true", help="ne pas chercher de mise à jour")
    parser.add_argument("--raccourci", action="store_true", help="créer le raccourci sur le bureau")
    parser.add_argument("--verifier", action="store_true", help="vérifier l'installation")
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

    cfg = load_config()
    if args.dossier:
        cfg["folder"] = str(Path(args.dossier).expanduser().resolve())
        save_config(cfg)
    folder = Path(cfg.get("folder") or default_folder())
    folder.mkdir(parents=True, exist_ok=True)

    port = args.port or cfg.get("port") or DEFAULT_PORT
    # Déjà ouvert ? On montre simplement la fenêtre.
    if is_mediavior(port):
        if not args.sans_fenetre:
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
    if FROZEN:
        web.APP_UPDATE = STATE  # « release » est rempli en arrière-plan s'il y a du nouveau
        web.APP_UPDATE_HOOK = lambda: install_app_update(STATE["release"], web.QUIT_HOOK)
    url = f"http://127.0.0.1:{port}/"

    def when_ready():
        for _ in range(100):
            if server.started:
                print(f"MediaVior est prêt : {url}", flush=True)
                if not args.sans_fenetre:
                    open_window(url)
                return
            time.sleep(0.1)

    threading.Thread(target=when_ready, daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
