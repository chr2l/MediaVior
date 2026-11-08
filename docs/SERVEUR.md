# MediaVior sur un serveur

La version serveur tourne dans un conteneur Docker. Pratique pour une maison : tout le monde
l'utilise depuis son navigateur ou son téléphone, et les fichiers restent sur le serveur.

> ⚠️ **Pas de mot de passe.** Garde MediaVior sur ton réseau local ou derrière un VPN (Tailscale,
> WireGuard…). Ne l'expose jamais sur Internet sans authentification devant (reverse proxy avec
> mot de passe, par exemple).

## Installer

```bash
git clone https://github.com/chr2l/MediaVior.git
cd MediaVior
docker compose up -d --build
```

L'appli écoute sur le port `8010` du serveur : ouvre `http://ADRESSE-DU-SERVEUR:8010`.
Les fichiers sont écrits dans `./telechargements` (à changer dans `docker-compose.yml`), monté
dans le conteneur sur `/downloads` : ils survivent aux redémarrages et aux mises à jour.

## Mises à jour

Le conteneur installe la dernière version de yt-dlp à chaque démarrage, et l'appli vérifie toutes
les 12 h si une nouvelle version est sortie. Si c'est le cas, elle attend que la file soit vide puis
s'arrête proprement : Docker la relance (`restart: unless-stopped`) avec la nouvelle version.
Pour désactiver ce comportement : `LECOFFRE_AUTO_UPDATE=0`.

Pour récupérer une nouvelle version de MediaVior : `git pull && docker compose up -d --build`.

## Sur téléphone

MediaVior peut s'installer comme une appli et apparaître dans le menu **Partager** d'Android
(YouTube → Partager → MediaVior). Les navigateurs n'autorisent ça qu'en **HTTPS** : en `http://`
le site marche, mais le bouton « Installer » n'apparaît pas.

Pour l'activer, mets l'appli derrière HTTPS, par exemple :
- **Tailscale** : `tailscale serve --bg 8010` sur le serveur donne une adresse
  `https://<machine>.<tailnet>.ts.net` accessible depuis tes appareils ;
- un reverse proxy (Nginx Proxy Manager, Caddy…) avec un nom de domaine **et une authentification**.

Puis ouvre l'adresse HTTPS dans Chrome sur Android → menu ⋮ → **Installer l'application**.

Pour juste tester sans HTTPS : dans Chrome Android, ouvre
`chrome://flags/#unsafely-treat-insecure-origin-as-secure`, ajoute l'adresse du serveur, relance.

**iPhone** : iOS ne propose pas d'appli web dans le menu Partager. Crée un raccourci dans l'app
Raccourcis : *Recevoir des URL depuis la feuille de partage* → *Ouvrir l'URL*
`http://ADRESSE-DU-SERVEUR:8010/?url=` suivi de *Entrée du raccourci*.

## Sécurité

Les liens qui pointent vers des adresses locales ou internes (localhost, 10.x, 192.168.x, 100.64.x,
etc.) sont refusés, pour que l'appli ne puisse pas servir à explorer ton réseau. La vérification
porte sur le lien collé : une redirection faite ensuite par le site lui-même n'est pas contrôlée.

L'image tourne en root et yt-dlp n'est pas figé : c'est voulu, pour que les mises à jour
s'installent toutes seules.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `LECOFFRE_DOWNLOAD_DIR` | `/downloads` | Dossier des fichiers |
| `LECOFFRE_AUTO_UPDATE` | `1` dans l'image | Redémarre quand une nouvelle version de yt-dlp sort |
| `FFMPEG_BIN`, `FFPROBE_BIN`, `TESSERACT_BIN` | `ffmpeg`, `ffprobe`, `tesseract` | Chemins des outils |
| `MEDIAVIOR_LOCAL` | absent | `1` = version PC (posé par `mediavior.py`) |

Les noms en `LECOFFRE_` viennent de l'ancien nom du projet ; ils sont gardés pour ne pas casser les
installations existantes.
