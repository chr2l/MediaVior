# Recette PyInstaller de l'appli prête à installer (Windows, Mac, Linux).
# Lancer depuis la racine du dépôt, après packaging/prepare.py :
#     pyinstaller --noconfirm packaging/mediavior.spec
import json
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
APP = ROOT / "app"
BUILD = ROOT / "build"
ICONS = APP / "static" / "icons"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

datas = [
    (str(APP / "templates"), "templates"),  # main.py les cherche à côté de lui
    (str(APP / "static"), "static"),
    (str(ROOT / "PROMPT.md"), "."),
    (str(ROOT / "PROMPT.en.md"), "."),
    (str(BUILD / "build.json"), "."),
]
datas += collect_data_files("certifi") + collect_data_files("yt_dlp_ejs")
binaries = [(str(p), "bin") for p in sorted((BUILD / "bin").iterdir())]
hiddenimports = (
    ["main", "jumelage", "websockets.asyncio.client"]
    + collect_submodules("uvicorn")
    + collect_submodules("yt_dlp")
    + collect_submodules("yt_dlp_ejs")
    + collect_submodules("aiortc")
)

a = Analysis(
    [str(ROOT / "mediavior.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy.tests"],
)
pyz = PYZ(a.pure)

# Fiche « Propriétés > Détails » de MediaVior.exe (nom, version, éditeur) : un programme
# sans cette fiche paraît plus suspect aux antivirus.
version_file = None
if IS_WIN:
    v = json.loads((BUILD / "build.json").read_text())["version"]
    nums = tuple((list(int(x) for x in v.split(".") if x.isdigit()) + [0, 0, 0, 0])[:4])
    (BUILD / "version.txt").write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[StringFileInfo([StringTable('040C04B0', [
    StringStruct('CompanyName', 'MediaVior (projet libre)'),
    StringStruct('FileDescription', 'MediaVior'),
    StringStruct('FileVersion', '{v}'),
    StringStruct('InternalName', 'MediaVior'),
    StringStruct('LegalCopyright', 'Licence AGPL-3.0'),
    StringStruct('OriginalFilename', 'MediaVior.exe'),
    StringStruct('ProductName', 'MediaVior'),
    StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])])
''', encoding="utf-8")
    version_file = str(BUILD / "version.txt")
icon = str(ICONS / ("mediavior.ico" if IS_WIN else "icon-512.png"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MediaVior",
    console=False,  # pas de fenêtre noire : l'appli s'ouvre dans le navigateur
    icon=icon,
    version=version_file,
    upx=False,  # fichiers compressés par UPX = souvent pris pour des virus
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="MediaVior")
if IS_MAC:
    app = BUNDLE(
        coll,
        name="MediaVior.app",
        icon=icon,
        bundle_identifier="io.github.chr2l.mediavior",
        info_plist={
            "CFBundleDisplayName": "MediaVior",
            "CFBundleShortVersionString": json.loads((BUILD / "build.json").read_text())["version"],
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
