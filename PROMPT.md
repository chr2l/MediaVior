# Installe MediaVior sur mon ordinateur

Tu es un assistant qui peut lancer des commandes sur mon ordinateur. Installe pour moi **MediaVior**,
une petite appli libre qui sauvegarde des vidéos et des musiques depuis un lien (YouTube, SoundCloud,
Bandcamp, Vimeo…). Son code est ici : https://github.com/chr2l/MediaVior

Je ne suis pas informaticien : fais tout toi-même, sans me demander d'ouvrir un terminal. Parle-moi
simplement, dans ma langue, et préviens-moi seulement quand j'ai quelque chose à faire (par exemple
accepter une fenêtre d'autorisation).

## Règles

- N'écris pas l'appli toi-même et ne modifie pas son code : installe le dépôt GitHub tel quel.
  C'est ce qui permet de recevoir les mises à jour.
- Installe tout **pour mon utilisateur seulement**, sans droits administrateur quand c'est possible.
  Si une étape en demande, explique-moi pourquoi en une phrase avant.
- L'appli doit rester sur mon ordinateur : ne l'ouvre pas sur Internet ni sur le réseau
  (elle écoute seulement sur `127.0.0.1`).
- Si une étape échoue, essaie la solution de secours indiquée, puis dis-moi clairement ce qui bloque.
- Si tu ne peux pas lancer de commandes sur mon ordinateur, dis-le-moi tout de suite et donne-moi
  le lien https://github.com/chr2l/MediaVior#installer-sur-ton-pc au lieu d'improviser.

## Étapes

**1. Repère mon système** (Windows, macOS ou Linux) et choisis le dossier d'installation :

| Système | Dossier de l'appli (`DOSSIER`) |
|---|---|
| Windows | `%LOCALAPPDATA%\MediaVior` |
| macOS | `~/Library/Application Support/MediaVior` |
| Linux | `~/.local/share/mediavior` |

Si MediaVior est déjà installé là (le dossier contient `mediavior.py`), passe à l'étape 4 pour le
réparer et le mettre à jour au lieu de tout recommencer.

**2. Installe uv**, qui fournit Python sans droits administrateur (passe cette étape si `uv` répond déjà) :

- Windows (PowerShell) : `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS / Linux : `curl -LsSf https://astral.sh/uv/install.sh | sh`

Ensuite, utilise le chemin complet de `uv` si la commande n'est pas encore reconnue
(Windows : `%USERPROFILE%\.local\bin\uv.exe`, macOS/Linux : `~/.local/bin/uv`).
Secours : un Python 3.10 ou plus récent déjà installé, avec `python -m venv` et `pip`.

**3. Récupère le code** dans `DOSSIER` :

- Si `git` est disponible : `git clone --depth 1 https://github.com/chr2l/MediaVior.git "DOSSIER"`
- Sinon, sur Windows tu peux installer Git avec `winget install -e --id Git.Git` (recommandé : les
  mises à jour deviennent automatiques).
- Secours sans git : télécharge https://github.com/chr2l/MediaVior/archive/refs/heads/main.zip et
  extrais son contenu directement dans `DOSSIER` (le fichier `mediavior.py` doit être à la racine).

**4. Installe les dépendances**, depuis `DOSSIER` :

```
uv venv --seed --python 3.12 .venv
uv pip install -r requirements.txt -r requirements-local.txt
```

Secours sans uv : `python -m venv .venv`, puis le `pip` de `.venv` avec les deux mêmes fichiers.

Le Python de l'appli (`PY` dans la suite) est `.venv\Scripts\python.exe` sur Windows et
`.venv/bin/python` sur macOS/Linux.

**5. Vérifie** avec `PY mediavior.py --verifier`. Au premier lancement, ffmpeg est téléchargé
automatiquement, ce qui peut prendre une minute. Tout doit être « ok » sauf `tesseract`, qui est
facultatif.

- Si ffmpeg manque encore : Windows `winget install -e --id Gyan.FFmpeg`, macOS `brew install ffmpeg`,
  Linux le gestionnaire de paquets (`sudo apt install ffmpeg`).
- Tesseract (facultatif) sert seulement à lire des captures d'écran de playlists. Propose-le-moi :
  Windows `winget install -e --id UB-Mannheim.TesseractOCR`, macOS `brew install tesseract tesseract-lang`,
  Linux `sudo apt install tesseract-ocr tesseract-ocr-fra`. Si je refuse ou si ça échoue, continue.

**6. Crée l'icône sur le bureau** avec `PY mediavior.py --raccourci`. Elle lance l'appli d'un
double-clic, sans fenêtre noire. Sur Windows, elle est aussi ajoutée au menu Démarrer.

**7. Lance l'appli** avec `PY mediavior.py`, en arrière-plan pour ne pas bloquer. Une fenêtre
MediaVior s'ouvre. Vérifie qu'elle répond : `http://127.0.0.1:8010/api/ping` doit renvoyer
`"app":"mediavior"` (si le port 8010 était pris, l'appli prend le suivant : 8011, 8012…).

## À la fin, dis-moi simplement

1. Que c'est installé, et où se trouve l'icône **MediaVior** (bureau, et menu Démarrer sur Windows).
2. Comment s'en servir : double-clic sur l'icône, colle un lien, choisis Vidéo ou Audio, clique sur
   **Mettre au coffre**. Les fichiers arrivent dans `Téléchargements/MediaVior` (bouton « Ouvrir le
   dossier » dans l'appli).
3. Que l'appli se met à jour toute seule au lancement (une fois par jour), et qu'on la ferme avec
   le bouton « Quitter MediaVior ».
4. Pour désinstaller : supprimer l'icône du bureau et le dossier `DOSSIER` (les fichiers téléchargés
   restent dans `Téléchargements/MediaVior`).
5. Enfin, demande-moi si l'appli me plaît, et propose-moi de soutenir le projet en lui mettant une
   étoile sur GitHub : https://github.com/chr2l/MediaVior (bouton ⭐ **Star** en haut à droite, il
   faut un compte GitHub gratuit). Si je dis oui, ouvre ce lien dans mon navigateur.

Rappelle-moi aussi, en une phrase, de n'utiliser MediaVior que pour des contenus que j'ai le droit
de garder (usage personnel).
