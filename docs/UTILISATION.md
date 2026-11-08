# Mode d'emploi

Ce guide vaut pour la version PC comme pour la version serveur.

## Télécharger un média

1. Colle un lien : l'analyse démarre toute seule (ou appuie sur **Entrée**). Le titre, la
   miniature et les résolutions disponibles s'affichent, avec la taille estimée de chaque option.
2. Choisis Vidéo ou Audio, la qualité et le format. Une courte explication s'affiche sous chaque choix :
   - **Vidéo** : *Original* (meilleure qualité, sans conversion, souvent WebM VP9/AV1), *MP4* (H.264 + AAC,
     lisible partout ; converti par le serveur si le site ne le fournit pas à cette qualité), *MOV*.
   - **Audio** : *Original* (piste du site sans réencodage, souvent Opus ou M4A : la meilleure qualité possible),
     *MP3* (320/192/128 kb/s, le plus compatible), *FLAC* (sans perte, pour l'archivage), *WAV* (non compressé,
     pour le montage). Titre, artiste et pochette sont intégrés au fichier (sauf WAV).
3. Clique sur **Télécharger** : le média part dans la file **En cours** (progression, vitesse,
   temps restant, bouton **Annuler**), puis arrive dans la **Bibliothèque**.

**Plusieurs liens d'un coup** : colle-les dans le champ (un par ligne, ou même noyés dans du texte).
Ils apparaissent dans une liste, tu choisis des options communes (la qualité est alors un maximum),
et tout part dans la file, traité un par un.

**Liste de sons** : écris des titres (« Artiste - Titre », un par ligne) ou ajoute des captures
d'écran de playlists (bouton, glisser-déposer ou Ctrl+V) : les titres y sont lus avec Tesseract et
ajoutés à la liste, que tu peux corriger. **Chercher et télécharger** cherche chaque titre sur
YouTube, le télécharge en MP3/WAV et met le tout dans un zip (dans la bibliothèque), avec une
barre de progression pendant la recherche. La liste est gardée telle quelle ; les sons introuvables
y sont signalés, avec la raison, et s'ouvrent dans une fenêtre de recherche YouTube intégrée pour
écouter les résultats et choisir la bonne vidéo (la loupe de chaque titre fait pareil). Une vidéo
choisie est téléchargée telle quelle à la recherche suivante.

**Bibliothèque** : tout ce qui est dans le dossier des téléchargements. Pour chaque fichier :
récupérer, éditer ou supprimer. En version PC, le bouton **Ouvrir le dossier** l'ouvre dans
l'explorateur.

**Éditeur** (icône ciseaux) : couper (poignées sur la forme d'onde, boutons « Début ici / Fin ici »,
ou saisie au dixième de seconde), fondus d'entrée/sortie (son et image), volume ±12 dB,
normalisation, suppression du son, extraction de l'audio en MP3/WAV. La **coupe rapide** évite le
réencodage : instantanée et sans perte, mais elle se cale sur l'image clé la plus proche.
L'original n'est jamais modifié : chaque montage crée un nouveau fichier dans la bibliothèque.
Réencoder une longue vidéo en 4K peut être lent sur une petite machine.

Les playlists ne sont pas prises en charge volontairement : colle les liens des vidéos.

## Extension Brave / Chrome

Le dossier `extension/` contient une extension (Brave, Chrome, Edge) : un clic sur son icône
envoie la page en cours à MediaVior, en choisissant Vidéo ou Audio, la qualité et le format
(les mêmes choix que sur le site). Aussi en clic droit sur une page ou un lien
(« Envoyer à MediaVior… ») et au clavier avec Alt+Maj+C.

Installation :
1. Ouvre `brave://extensions` et active le **Mode développeur** (en haut à droite).
2. **Charger l'extension non empaquetée** → choisis le dossier `extension/` (dézippé).
3. La page de réglages s'ouvre : vérifie l'adresse de MediaVior (`http://127.0.0.1:8010`
   par défaut, celle de la version PC ; mets l'adresse de ton serveur sinon), clique **Enregistrer et tester** et accepte la demande d'accès.
4. Épingle l'icône (pièce de puzzle → punaise).

MediaVior accepte les appels venant d'une extension (CORS limité aux origines
`chrome-extension://`). Pour mettre l'extension à jour : remplace le dossier puis clique sur ↻
dans `brave://extensions`.

## Sur téléphone

Le téléphone utilise la version serveur (voir [SERVEUR.md](SERVEUR.md#sur-téléphone)) : MediaVior
s'y installe comme une appli et apparaît dans le menu **Partager**.

## Depuis n'importe quelle page (favori)

Un favori-marque-page envoie la page en cours à MediaVior. Crée un favori avec cette adresse
(remplace l'adresse si MediaVior n'est pas sur ce PC) :

```
javascript:location.href='http://127.0.0.1:8010/?url='+encodeURIComponent(location.href)
```

## Mises à jour

`yt-dlp` doit rester à jour : les sites changent leur structure et cassent l'extraction sans
prévenir.

- **Version PC** : au lancement (une fois par jour au plus), le lanceur récupère la dernière version
  de MediaVior (`git pull`) et de yt-dlp, en arrière-plan. Elles servent au lancement suivant.
- **Version serveur** : voir [SERVEUR.md](SERVEUR.md#mises-à-jour).

La version de yt-dlp utilisée est affichée en bas de la barre latérale.

## Fermer, désinstaller

- **Fermer** : bouton « Quitter MediaVior » en bas de la barre latérale. Fermer la fenêtre seule
  laisse l'appli tourner en fond (un double-clic sur l'icône la rouvre aussitôt).
- **Désinstaller** : supprime l'icône du bureau et le dossier de l'appli (`%LOCALAPPDATA%\MediaVior`
  sur Windows, `~/Library/Application Support/MediaVior` sur macOS, `~/.local/share/mediavior` sur
  Linux si elle a été installée par le prompt), puis `~/.mediavior` (réglages). Tes fichiers restent
  dans `Téléchargements/MediaVior`.
