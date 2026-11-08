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
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
HOME_DIR = Path.home() / ".mediavior"
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

    if IS_WIN:
        # pythonw : pas de fenêtre noire de console
        pyw = Path(sys.executable).with_name("pythonw.exe")
        target = pyw if pyw.is_file() else Path(sys.executable)
        q = lambda v: str(v).replace("'", "''")  # échappement PowerShell
        ps = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @('{q(desk)}', [Environment]::GetFolderPath('Programs'))) {{
  $s = $ws.CreateShortcut((Join-Path $dir 'MediaVior.lnk'))
  $s.TargetPath = '{q(target)}'
  $s.Arguments = '"{q(script)}"'
  $s.WorkingDirectory = '{q(ROOT)}'
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
        entry = f"""[Desktop Entry]
Type=Application
Name=MediaVior
Comment=Sauvegarde tes médias
Exec="{sys.executable}" "{script}"
Path={ROOT}
Icon={icons / "icon-512.png"}
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
    os.environ["MEDIAVIOR_LOCAL"] = "1"
    os.environ["LECOFFRE_DOWNLOAD_DIR"] = str(folder)
    os.environ["LECOFFRE_AUTO_UPDATE"] = "0"  # en local, c'est ce lanceur qui met à jour
    if not args.sans_maj:
        update_in_background(cfg)

    sys.path.insert(0, str(APP_DIR))
    import uvicorn
    import main as web  # app/main.py

    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="warning"))
    web.QUIT_HOOK = lambda: setattr(server, "should_exit", True)
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
