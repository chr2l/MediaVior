"""Prépare la construction de l'appli prête à installer (appelé par GitHub, voir
.github/workflows/installeurs.yml) : copie ffmpeg, ffprobe et deno dans build/bin, et écrit
build/build.json (version de l'appli et de yt-dlp inclus).

    python packaging/prepare.py 1.2.0
"""
import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import deno
import static_ffmpeg.run

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BIN = BUILD / "bin"


def main() -> None:
    app_version = (sys.argv[1] if len(sys.argv) > 1 else "0.0.0").lstrip("v")
    shutil.rmtree(BIN, ignore_errors=True)
    BIN.mkdir(parents=True)
    ffmpeg, ffprobe = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
    for tool in (ffmpeg, ffprobe, deno.find_deno_bin()):
        dest = BIN / Path(tool).name
        shutil.copy2(tool, dest)
        dest.chmod(0o755)
        print(f"{dest.name} : {dest.stat().st_size // 1_000_000} Mo")
    info = {"version": app_version, "yt_dlp": version("yt-dlp")}
    (BUILD / "build.json").write_text(json.dumps(info), encoding="utf-8")
    print(info)


if __name__ == "__main__":
    main()
