#!/bin/sh
# Point d'entrée de l'AppImage : lance l'appli rangée dans usr/lib/mediavior.
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/mediavior/MediaVior" "$@"
