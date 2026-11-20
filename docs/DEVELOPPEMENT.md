# Lire et modifier le code

MediaVior est volontairement simple : un seul fichier Python pour le serveur, du HTML/CSS/JS sans
framework ni étape de build pour l'interface. Ce guide te donne la carte pour t'y retrouver.

## Vue d'ensemble

```
navigateur ──HTTP──► app/main.py (FastAPI)
                        │  file d'attente (asyncio) ─► yt-dlp ─► ffmpeg
                        │  bibliothèque = dossiers sur le disque (meta.json)
                        ▼
              dossier des téléchargements
```

Deux façons de lancer le même serveur :

- **Appli installée** (`.exe`, `.dmg`, AppImage) : le même `mediavior.py`, figé avec PyInstaller
  (`packaging/`). `FROZEN` y est vrai : ffmpeg/deno viennent du paquet, et yt-dlp est mis à jour
  en téléchargeant son `.whl` dans `~/.mediavior/yt-dlp`.
- **Version PC** : `mediavior.py` démarre `app/main.py` sur `127.0.0.1`, ouvre une fenêtre et pose
  `MEDIAVIOR_LOCAL=1` (boutons « Ouvrir le dossier » / « Quitter », protection contre les autres
  sites).
- **Version serveur** : `Dockerfile` + `entrypoint.sh` lancent `uvicorn main:app` sur le port 8000
  du conteneur.
  Avec `MEDIAVIOR_APERCU=1`, le site devient une vitrine : les visiteurs arrivent sur
  `vitrine.html` (présentation, boutons d'installation, questions), et l'interface reste visible
  en aperçu sur `/apercu` : les actions proposent de télécharger l'appli et le coffre paraît vide. Seule une requête
  avec `X-Elie-Role: admin` garde l'outil complet. À n'activer que derrière la porte d'elie.place,
  qui pose et filtre cet en-tête.

## Carte des fichiers

| Fichier | Contenu |
|---|---|
| `app/main.py` | Tout le serveur, découpé en sections commentées : modèles, mise à jour de yt-dlp, pages, version locale, sécurité des liens, bibliothèque, analyse, file d'attente, téléchargement, éditeur, liste de sons |
| `app/templates/index.html` | La page principale : Télécharger (trois façons : un lien, plusieurs liens en zip, liste de titres) et le panneau de droite (En cours, Bibliothèque) |
| `app/templates/editor.html` | L'éditeur (coupe, fondus, volume) |
| `app/templates/legal.html` | Mentions légales, avec sommaire latéral |
| `app/templates/vitrine.html`, `app/static/vitrine.css`, `app/static/vitrine.js` | Vitrine du site public (page d'accueil des visiteurs, aussi visible sur `/vitrine`). Captures de l'appli dans `app/static/vitrine/` |
| `app/static/i18n.js`, `app/static/i18n-en.js` | Langue de l'interface (français ou anglais) et traduction anglaise : voir « Traduction » plus bas |
| `app/static/common.js` | Outils partagés : `api()`, `h()` (création d'éléments sans `innerHTML`), icônes |
| `app/static/shell.js` | Navigation (panneau de droite sur ordinateur, onglets du bas sur téléphone), pastilles, notifications |
| `app/static/app.js` | Analyse, options, file d'attente, bibliothèque |
| `app/static/formats.js`, `app/static/formats.css` | Listes avec le signet « préféré » : format du son, format de la vidéo, qualité de la vidéo. Le préféré est gardé par l'appli (`/api/preferences`, fichier `preferences.json` à côté de l'historique) : la page, l'extension et le téléphone relié voient le même. Copies identiques dans `relais/public/` et `extension/` |
| `app/static/sons.js` | Liste de sons, captures d'écran, fenêtre de choix YouTube |
| `app/static/tags.js` | Fenêtre « Infos du morceau » (titre, interprètes, album, pochette) et bouton « Ajouter mes sons » (glisser-déposer sur le coffre) |
| `app/static/editor.js` | Forme d'onde et commandes de l'éditeur |
| `app/static/local.js` | Boutons de la version PC et fenêtre « Copier le prompt » |
| `app/static/liens.js` | Version PC seulement : ouvre les liens vers d'autres sites dans le navigateur par défaut de l'ordinateur (et non dans la fenêtre Edge/Chrome de l'appli) |
| `app/static/sw.js` | Service worker (appli installable). Change `CACHE` quand tu modifies l'interface |
| `mediavior.py` | Lanceur PC : options, ffmpeg de secours, mises à jour, fenêtre, raccourci bureau. Fenêtre : sous Windows, MediaVior a sa propre fenêtre (`native_window`, pywebview + WebView2, processus à part `MediaVior.exe --fenetre URL`) sans la barre de Windows : la page dessine la sienne (`.titlebar`, boutons réduire / agrandir / fermer, `app-region: drag` pour glisser) et `_remove_windows_title_bar` garde bords, ombre et collage aux bords de l'écran ; sinon (Mac, Linux, ou WebView2 absent) fenêtre Edge/Chrome : l'appli installée du navigateur (`--app-id`, Réglages > « Fenêtre aux couleurs de MediaVior ») ou `--app=` |
| `app/jumelage.py` | Téléphone relié (version PC) : QR code, connexion au relais, messages chiffrés, envoi des fichiers en WebRTC (aiortc) |
| `relais/` | Relais Cloudflare (`src/worker.js`, un Durable Object par paire PC + téléphones) et page du téléphone (`public/`). Voir `relais/README.md` |
| `packaging/` | Installeurs : recette PyInstaller, installeur Windows (Inno Setup), AppImage. Construits par `.github/workflows/installeurs.yml` à chaque push sur `main` |
| `extension/` | Extension Manifest V3, sans dépendance. `page.js` : bouton sur YouTube, SoundCloud, Vimeo, Bandcamp, Dailymotion, Spotify, Deezer |
| `packaging/extension_firefox.py` | Manifest Firefox (même code), signé par Mozilla dans `installeurs.yml` (secrets `AMO_JWT_ISSUER` / `AMO_JWT_SECRET`) |
| `pinokio.js`, `install.js`, `start.js`, `update.js` | Scripts [Pinokio](https://pinokio.co) |

## Principes

- **Pas de base de données** : les médias finis sont rangés directement dans le dossier des
  téléchargements (MediaChest). Leur fiche est dans `.mediavior/<id>/meta.json` (dossier caché,
  qui sert aussi au téléchargement en cours) ; `meta.json` retient le nom du média (`file`). La
  bibliothèque relit le disque. Un média effacé depuis l'explorateur disparaît au lancement suivant.
- **Version PC** : MediaChest est à côté de l'appli installée (MediaVior.exe, AppImage), sinon dans
  Téléchargements (Mac, prompt, Pinokio). Installeur Windows : `C:\Users\<nom>\MediaVior`.
- **Jobs en mémoire** : un seul worker traite la file, un média à la fois. Suffisant pour un usage
  personnel ; au redémarrage, les jobs inachevés sont nettoyés.
- **Pas de `innerHTML` avec des données externes** : les titres viennent de sites tiers, on passe
  par `h()`.
- **Liens filtrés** : `_safe_url()` refuse les adresses locales ou internes.
- **yt-dlp jamais figé** : il se met à jour seul (`entrypoint.sh`, vérification PyPI, lanceur PC).
- **Erreur 403** : `_run_ytdlp` (app/main.py) réessaie une fois, cache de yt-dlp vidé et autres clients YouTube (`RETRY_403_CLIENTS`). L'appli PC cherche un nouveau yt-dlp à chaque lancement puis toutes les 6 h ; s'il attend d'être chargé, le message d'erreur demande de relancer MediaVior.
- **Meilleure qualité du son** : `AUDIO_FORMAT` prend d'abord un fichier sans perte si le site en fournit un (Bandcamp gratuit ou à prix libre, Jamendo, Archive.org, fichier de l'artiste sur SoundCloud), sinon la meilleure piste. `/api/analyze` renvoie `audio_best` (codec, débit, sans perte) : la page affiche la vraie qualité et ne dit jamais « original » pour un son compressé.
- **Chercher une meilleure source** (bouton sous le choix du son) : `/api/meilleure-source` cherche « Artiste Titre » (`_music_query`) sur Bandcamp (API de recherche du site) et SoundCloud (`scsearch`), lit la qualité de chaque résultat et range le sans perte en premier. La personne choisit : un résultat peut être un remix.
- **Infos du morceau** (bouton étiquette sur chaque son du coffre) : `_read_tags` / `_write_tags` lisent et écrivent titre, interprètes, album, année, genre, piste et pochette avec mutagen (MP3, AIFF, WAV, FLAC, M4A, Opus, Ogg ; ID3v2.3 pour MP3/AIFF/WAV). `/api/tags/search` cherche sur MusicBrainz (une requête par seconde au plus, pochettes Cover Art Archive) et Deezer, sans clé ni compte. Les pochettes ne sont téléchargées que depuis ces sites (`COVER_HOSTS`). « Ajouter mes sons » (`/api/library/import`, corps brut = le fichier) range le fichier dans le coffre ; `_auto_tags` complète seulement les champs vides ou mal faits, et seulement si titre, artiste et durée correspondent. Après chaque téléchargement de son, `_auto_album` ajoute ainsi l'album s'il manque.
- **Sources avec abonnement** (Réglages, version PC, si `streamrip` ou `votify` est installé) : un lien de **morceau** Qobuz ou Deezer passe par streamrip (FLAC), un lien de morceau Spotify par Votify (session librespot, cookie `sp_dc` d'un compte Premium, OGG Vorbis jusqu'à 320 kb/s). Identifiants dans `streamrip.json` à côté de l'historique (droits 600, jamais renvoyés à la page ; mot de passe Qobuz en md5, comme streamrip l'attend). `_fetch_streamrip` lance l'outil (`_tool_command`), puis `_tool_convert` passe par ffmpeg si un autre format est choisi. En cas d'échec, `_fetch_media` retombe sur yt-dlp. SoundCloud, albums et listes restent à yt-dlp. Absent de l'appli figée et de la version serveur. Pas de Tidal (connexion à valider dans le navigateur), pas de FLAC Spotify (demande des fichiers de déchiffrement).
- **Avertissement** (`#riskDialog`, `askRisk()` dans `local.js`) : avant d'activer la connexion du navigateur ou d'enregistrer un identifiant, la personne coche « J'ai compris et j'en prends l'entière responsabilité ». Le serveur refuse sans `accept_risks: true`.
- **Connexion du navigateur** (Réglages, version PC) : `connexion.json` à côté de l'historique garde le navigateur choisi ; `_open_ydl` passe ses cookies à yt-dlp (YouTube Premium 256 kb/s, fichier SoundCloud de l'artiste). Si la lecture échoue, le téléchargement continue sans, et l'erreur s'affiche dans les Réglages.

## Traduction (français / anglais)

L'interface s'affiche en français ou en anglais : la langue du navigateur ou du système par défaut
(français si elle commence par « fr », anglais sinon), puis le choix fait avec le lien
« English / Français » en bas de page (gardé dans le navigateur).

- Les textes restent **écrits en français** dans le HTML et le JS.
- `app/static/i18n-en.js` contient la traduction : la clé est la phrase française exacte.
- Dans le HTML, rien à faire de plus : `translateDom()` traduit les textes et les attributs
  (`placeholder`, `title`, `aria-label`, `alt`) trouvés dans le dictionnaire.
- Dans le JS, passe par `t("Phrase avec {n} fichiers", { n })`. Pour un pluriel, deux phrases :
  `t(n > 1 ? "{n} fichiers" : "{n} fichier", { n })`.
- Les messages d'erreur du serveur (`app/main.py`) restent en français : ils sont traduits côté
  navigateur, avec le même dictionnaire (et `I18N_EN_PATTERNS` quand ils contiennent un nombre).
- Un lien vers une doc qui existe en anglais : ajoute `data-href-en="…"` à côté de `href`.
- Une phrase absente du dictionnaire reste en français : rien ne casse.

Même moteur, copié, pour la page du téléphone (`relais/public/i18n*.js`) et l'extension
(`extension/i18n*.js`, plus `extension/_locales/` pour le nom, le menu clic droit et les boutons sur les sites). Le prompt
d'installation existe en deux versions : `PROMPT.md` et `PROMPT.en.md`, à garder pareilles.

## Vitrine (site public)

`app/templates/vitrine.html` est la page d'accueil des visiteurs. Elle reste **courte**, façon page
produit : une phrase, un bouton de téléchargement, une grande capture de l'appli, deux cartes
(ordinateur, téléphone), une ligne « pourquoi chez toi », les liens de téléchargement en lignes,
quatre questions. Pas de longues listes d'arguments ni de grilles d'icônes.

Sites de référence pour la présenter simplement :

- [Google Antigravity](https://antigravity.google/) : une phrase en titre, les produits en
  quelques cartes courtes avec une image chacune.
- [Claude, page Télécharger](https://claude.com/download) : un titre, un bouton, puis une ligne
  par système avec son bouton, et une FAQ courte.

La capture vient de l'appli en aperçu, remplie de médias d'exemple (`app/static/vitrine/`).

## Lancer en développement

```bash
uv venv --seed .venv && uv pip install -r requirements.txt -r requirements-local.txt
.venv/bin/python mediavior.py --sans-fenetre --sans-maj --dossier ./telechargements
```

Puis ouvre l'adresse affichée. Relance après chaque modification de `main.py` ; les fichiers de
`app/static/` sont relus à chaque chargement de page.

Vérification minimale avant une pull request :

```bash
python -m py_compile app/main.py mediavior.py
```

Il n'y a pas encore de tests automatiques : décris dans la PR ce que tu as essayé à la main.

## Branches

- `main` : la version publiée, celle qu'installent le prompt et Pinokio.
- `dev` : le travail en cours. Les pull requests visent `dev`, qui est fusionné dans `main` une fois
  testé.
