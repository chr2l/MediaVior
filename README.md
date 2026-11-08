<p align="center">
  <img src="app/static/icons/icon-192.png" width="96" alt="">
</p>

<h1 align="center">MediaVior</h1>

<p align="center"><strong>Media Savior</strong> : sauvegarde une vidéo ou une musique avant qu'elle ne disparaisse.<br>
Tu colles un lien, tu cliques sur Télécharger. Ça tourne sur ton PC, pas chez quelqu'un d'autre.</p>

<p align="center">
  <a href="#installer-sur-ton-pc">Installer</a> ·
  <a href="docs/UTILISATION.md">Mode d'emploi</a> ·
  <a href="docs/SERVEUR.md">Sur un serveur</a> ·
  <a href="docs/DEVELOPPEMENT.md">Lire le code</a> ·
  <a href="CONTRIBUTING.md">Contribuer</a>
</p>

---

MediaVior récupère les médias de YouTube, SoundCloud, Bandcamp, Vimeo et de
[la plupart des sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) pris en
charge par [yt-dlp](https://github.com/yt-dlp/yt-dlp), dans la qualité et le format de ton choix.

- **Vidéo** : meilleure qualité d'origine, MP4 lisible partout, ou MOV pour le montage.
- **Audio** : piste d'origine, MP3 (320/192/128 kb/s), FLAC ou WAV, avec titre, artiste et pochette.
- **Plusieurs liens d'un coup**, qui partent dans une file d'attente.
- **Liste de sons** : écris des titres ou ajoute des captures d'écran de playlists ; chaque son est
  retrouvé sur YouTube et rangé dans un zip.
- **Bibliothèque** avec recherche, sélection multiple et un **éditeur** (coupe, fondus, volume,
  extraction de l'audio).
- **Extension Brave/Chrome** pour envoyer la page en cours d'un clic.

Pas de compte, pas de publicité, aucune donnée envoyée au projet.

## Installer sur ton PC

### En un prompt (le plus simple)

1. Ouvre une IA qui peut agir sur ton ordinateur : **Claude Desktop** (avec Claude Code), **ChatGPT
   Codex**, **Cursor**, **Windsurf**… Un simple chat dans le navigateur ne suffit pas : il faut
   qu'elle puisse lancer des commandes.
2. Copie tout le contenu de [**PROMPT.md**](PROMPT.md) (bouton « Copy raw file » en haut à droite du
   fichier) et colle-le dans l'IA.
3. Elle installe tout et crée une icône **MediaVior** sur ton bureau. Double-clic dessus, colle un
   lien, c'est parti.

Le prompt demande à l'IA d'installer ce dépôt tel quel, sans réécrire l'appli : tout le monde a la
même version, et elle se met à jour toute seule.

### Avec Pinokio

[Pinokio](https://pinokio.co) installe des applis en un clic. Dans Pinokio : **Discover** →
**Download from URL** → colle `https://github.com/chr2l/MediaVior` → **Installer**, puis **Lancer**.

### À la main

Il faut Python 3.10 ou plus récent (ou [uv](https://docs.astral.sh/uv/)) et git.

```bash
git clone https://github.com/chr2l/MediaVior.git
cd MediaVior
uv venv --seed --python 3.12 .venv            # ou : python -m venv .venv
uv pip install -r requirements.txt -r requirements-local.txt
.venv/bin/python mediavior.py --verifier     # Windows : .venv\Scripts\python.exe
.venv/bin/python mediavior.py --raccourci    # icône sur le bureau
.venv/bin/python mediavior.py                # lance l'appli
```

ffmpeg est téléchargé automatiquement s'il n'est pas déjà installé. Tesseract (lecture des
captures d'écran) est facultatif. Les fichiers vont dans `Téléchargements/MediaVior` ; pour en
changer : `mediavior.py --dossier "D:\Mes médias"`.

### Sur un serveur

Pour une maison ou une petite équipe, MediaVior tourne aussi dans un conteneur Docker :
voir [docs/SERVEUR.md](docs/SERVEUR.md).

## Organisation du dépôt

| Chemin | Rôle |
|---|---|
| [`app/main.py`](app/main.py) | Le serveur (FastAPI) : analyse, file de téléchargement, bibliothèque, éditeur, liste de sons |
| [`app/templates/`](app/templates), [`app/static/`](app/static) | L'interface (HTML, CSS, JavaScript sans framework) |
| [`mediavior.py`](mediavior.py) | Le lanceur de la version PC : fenêtre, raccourci, mises à jour |
| [`PROMPT.md`](PROMPT.md) | Le prompt d'installation à coller dans une IA |
| [`pinokio.js`](pinokio.js), `install.js`, `start.js`, `update.js` | Les scripts Pinokio |
| [`extension/`](extension) | L'extension Brave/Chrome |
| `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` | La version serveur |
| [`docs/`](docs) | Mode d'emploi, serveur, développement |

## Sécurité et usage

- La version PC n'écoute que sur ton ordinateur (`127.0.0.1`) et refuse les requêtes venant
  d'autres sites.
- L'appli n'a pas de mot de passe : sur un serveur, ne l'expose jamais sur Internet sans protection
  devant (voir [docs/SERVEUR.md](docs/SERVEUR.md)).
- Une faille ? Voir [SECURITY.md](SECURITY.md).

MediaVior est fait pour un **usage personnel** : sauvegarder tes propres contenus, des médias que
tu as le droit de conserver, ou des choses menacées de disparition. Respecte le droit d'auteur et
les conditions d'utilisation de chaque site. Détails dans les mentions légales (lien en bas de
l'appli, page `/legal`).

## Soutenir le projet

Si MediaVior te rend service, mets-lui une ⭐ en haut de cette page : ça aide d'autres personnes à
le trouver. Les retours et les propositions sont les bienvenus dans les
[issues](https://github.com/chr2l/MediaVior/issues) et les pull requests.

Licence : [AGPL-3.0](LICENSE). Tu peux utiliser, modifier et partager MediaVior librement ; si tu publies ou mets en ligne une version modifiée, son code doit rester ouvert sous la même licence.
