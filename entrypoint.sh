#!/bin/sh
# Met yt-dlp à jour à chaque démarrage du conteneur (les sites cassent régulièrement les anciennes versions).
# Sans réseau, on garde simplement la version déjà installée.
if [ "$LECOFFRE_AUTO_UPDATE" = "1" ]; then
  timeout 180 pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -q -U "yt-dlp[default]" \
    || echo "Mise à jour de yt-dlp impossible : la version installée est conservée."
fi
exec uvicorn main:app --host 0.0.0.0 --port 8000
