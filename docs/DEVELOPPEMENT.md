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
| `app/static/sons.js` | Liste de sons, captures d'écran, fenêtre de choix YouTube |
| `app/static/editor.js` | Forme d'onde et commandes de l'éditeur |
| `app/static/local.js` | Boutons de la version PC et fenêtre « Copier le prompt » |
| `app/static/sw.js` | Service worker (appli installable). Change `CACHE` quand tu modifies l'interface |
| `mediavior.py` | Lanceur PC : options, ffmpeg de secours, mises à jour, fenêtre, raccourci bureau |
| `app/jumelage.py` | Téléphone relié (version PC) : QR code, connexion au relais, messages chiffrés, envoi des fichiers en WebRTC (aiortc) |
| `relais/` | Relais Cloudflare (`src/worker.js`, un Durable Object par paire PC + téléphones) et page du téléphone (`public/`). Voir `relais/README.md` |
| `packaging/` | Installeurs : recette PyInstaller, installeur Windows (Inno Setup), AppImage. Construits par `.github/workflows/installeurs.yml` à chaque push sur `main` |
| `extension/` | Extension Manifest V3, sans dépendance |
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
(`extension/i18n*.js`, plus `extension/_locales/` pour le nom et le menu clic droit). Le prompt
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
