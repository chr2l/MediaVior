"""Prépare la version Firefox de l'extension (dossier extension/).

Usage : python packaging/extension_firefox.py VERSION DOSSIER_DE_SORTIE

Firefox lit le même code que Chrome ; seul le manifest change :
- un script d'arrière-plan à la place du « service worker » de Chrome ;
- un identifiant fixe et l'adresse des mises à jour (firefox-updates.json, joint à chaque
  version publiée sur GitHub) : Firefox met l'extension à jour tout seul.
Écrit DOSSIER/firefox/ (à faire signer par Mozilla) et DOSSIER/firefox-updates.json.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/chr2l/MediaVior"
ADDON_ID = "mediavior@chr2l.github.io"


def main() -> None:
    version, out = sys.argv[1], Path(sys.argv[2])
    target = out / "firefox"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(ROOT / "extension", target, ignore=shutil.ignore_patterns("*.zip", ".*"))

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version  # ex. 2026.11.11.8 : toujours croissante, comme les installeurs
    manifest["background"] = {"scripts": ["background.js"], "type": "module"}
    manifest["browser_specific_settings"] = {
        "gecko": {
            "id": ADDON_ID,
            "strict_min_version": "128.0",
            "update_url": f"{REPO}/releases/latest/download/firefox-updates.json",
            "data_collection_permissions": {"required": ["none"]},
        }
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    updates = {"addons": {ADDON_ID: {"updates": [{
        "version": version,
        "update_link": f"{REPO}/releases/download/v{version}/MediaVior-Firefox.xpi",
    }]}}}
    (out / "firefox-updates.json").write_text(json.dumps(updates, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
