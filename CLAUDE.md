# Consignes pour Claude — MediaVior

- Français simple, phrases courtes : le mainteneur ne code pas. Carte du code : docs/DEVELOPPEMENT.md (lire la section utile, pas tout).
- Appli FastAPI + yt-dlp + ffmpeg : `app/main.py`, pages dans `app/templates/`, `app/static/`. Lanceur PC : `mediavior.py`. Extension : `extension/`. Pinokio : `pinokio.js` + `install.js`/`start.js`/`update.js`.
- `PROMPT.md` est le prompt d'installation collé par les utilisateurs dans leur IA : le garder précis et à jour si l'installation change.
- Vérifier : `python -m py_compile app/main.py mediavior.py` (pas de tests automatiques).
- Branches `claude/*` : PR vers `dev`. `dev` → `main` une fois testé ; `main` est la version publique installée par le prompt.
- Dépôt public : jamais d'adresse IP, de chemin de serveur, d'e-mail ni de secret dans les fichiers ou les PR.
- Aucune authentification : ne jamais proposer d'exposer l'appli sur Internet sans protection devant.
- yt-dlp se met à jour seul ; ne pas le figer.
- Modifications ciblées (Edit) ; ouvrir seulement les fichiers concernés.

- rtk actif (hook) : sortie Bash compressée auto. Sortie brute : `rtk bypass <cmd>`. Read/Grep/Glob non concernés.
