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

La page **Télécharger** propose trois façons, au choix en haut : **Un lien**, **Plusieurs liens**
et **Liste de titres**. Sur ordinateur, le panneau de droite montre en permanence ce qui est
**En cours** et la **Bibliothèque** ; sur téléphone, ce sont les onglets du bas.

**Plusieurs liens** : colle-les dans le champ (un par ligne, ou même noyés dans du texte ; coller
plusieurs liens dans « Un lien » y bascule tout seul). Choisis un format commun (la qualité est alors
un maximum) : les liens sont téléchargés un par un et rangés dans **un seul zip**, dans la
bibliothèque. Un lien qui échoue n'arrête pas les autres.

**Liste de titres** : écris des titres (« Artiste - Titre », un par ligne) ou ajoute des captures
d'écran de playlists (bouton, glisser-déposer ou Ctrl+V) : les titres y sont lus avec Tesseract et
ajoutés à la liste, que tu peux corriger. **Chercher et télécharger** cherche chaque titre sur
YouTube, le télécharge en MP3/WAV et met le tout dans un zip (dans la bibliothèque), avec une
barre de progression pendant la recherche. La liste est gardée telle quelle ; les sons introuvables
y sont signalés, avec la raison, et s'ouvrent dans une fenêtre de recherche YouTube intégrée pour
écouter les résultats et choisir la bonne vidéo (la loupe de chaque titre fait pareil). Une vidéo
choisie est téléchargée telle quelle à la recherche suivante.

**Bibliothèque** : tout ce qui est dans le dossier des téléchargements, rangé par jour. Sous chaque
titre : le format et la durée. Pour chaque fichier : retélécharger, éditer ou enlever. En version PC, le bouton **Ouvrir le dossier** l'ouvre dans
l'explorateur.

**Éditeur** (icône ciseaux) : couper (poignées sur la forme d'onde, boutons « Début ici / Fin ici »,
ou saisie au dixième de seconde), fondus d'entrée/sortie (son et image), volume ±12 dB,
normalisation, suppression du son, extraction de l'audio en MP3/WAV. La **coupe rapide** évite le
réencodage : instantanée et sans perte, mais elle se cale sur l'image clé la plus proche.
L'original n'est jamais modifié : chaque montage crée un nouveau fichier dans la bibliothèque.
Réencoder une longue vidéo en 4K peut être lent sur une petite machine.

Les playlists ne sont pas prises en charge volontairement : colle les liens des vidéos.

## Extension de navigateur (Chrome, Brave, Edge, Opera, Vivaldi)

Un clic sur l'icône de l'extension envoie la page en cours à MediaVior, en choisissant Vidéo ou
Audio, la qualité et le format. Aussi en clic droit sur une page ou un lien
(« Envoyer à MediaVior… ») et au clavier avec Alt+Maj+C.

Elle n'est pas sur le Chrome Web Store : elle est fournie avec l'appli.

Installation, une seule fois :
1. Dans MediaVior, clique sur **Navigateur**, puis sur **Préparer l'extension**. Le dossier
   `Documents/MediaVior extension` s'ouvre.
2. Dans le navigateur, ouvre `chrome://extensions` et active le **Mode développeur** (en haut à droite).
3. **Charger l'extension non empaquetée** → choisis le dossier `MediaVior extension`.
4. Épingle l'icône (pièce de puzzle → punaise).

Rien à régler : l'extension trouve MediaVior toute seule sur ce PC (port 8010 ou suivant).
L'appli recopie ce dossier à chaque lancement, donc l'extension suit ses mises à jour (elles
s'appliquent au prochain redémarrage du navigateur). Pour viser un MediaVior installé sur un autre
ordinateur, change l'adresse dans les réglages de l'extension (⚙).

Sans l'appli : `MediaVior-extension.zip` est joint à chaque version sur la page Releases de GitHub
(à dézipper, puis étapes 2 à 4).

MediaVior accepte les appels venant d'une extension (CORS limité aux origines
`chrome-extension://`).

## Sur téléphone

Relie ton téléphone à MediaVior sur ton PC, comme WhatsApp Web. C'est à faire une seule fois, sans
compte, et ça marche partout (4G comprise), pas seulement sur le wifi de la maison.

1. Dans l'appli PC, clique sur **Téléphone** (en haut). Un QR code s'affiche.
2. Scanne-le avec l'appareil photo du téléphone et touche le lien : la page MediaVior s'ouvre, déjà
   reliée.
3. Ajoute-la à l'écran d'accueil quand elle le propose (Android : un bouton ; iPhone : Partager →
   **Sur l'écran d'accueil**).

Ensuite, colle un lien et touche **Mettre au coffre** : le PC télécharge. Sur Android, tu peux aussi
faire **Partager → MediaVior** depuis YouTube. Quand c'est prêt, **Récupérer** envoie le fichier
directement du PC au téléphone.

Bon à savoir :

- Le PC doit être allumé, avec MediaVior ouvert.
- Les messages passent par un petit relais gratuit (dossier [`relais/`](../relais)), **chiffrés de
  bout en bout** : la clé est dans le QR code, le relais ne peut pas les lire. Les fichiers, eux, ne
  passent pas par le relais.
- Sur certains réseaux (wifi d'entreprise, certaines box 4G), la connexion directe PC → téléphone
  est bloquée : le fichier reste alors sur le PC.
- **Oublier les téléphones reliés** (dans la fenêtre Téléphone) déconnecte tous les téléphones et
  change la clé.

Avec la version serveur, le téléphone peut aussi utiliser le serveur directement (voir
[SERVEUR.md](SERVEUR.md#sur-téléphone)).

## Depuis n'importe quelle page (favori)

Un favori-marque-page envoie la page en cours à MediaVior. Crée un favori avec cette adresse
(remplace l'adresse si MediaVior n'est pas sur ce PC) :

```
javascript:location.href='http://127.0.0.1:8010/?url='+encodeURIComponent(location.href)
```

## Mises à jour

`yt-dlp` doit rester à jour : les sites changent leur structure et cassent l'extraction sans
prévenir.

- **Appli installée** (`.exe`, `.dmg`, AppImage) : yt-dlp est téléchargé une fois par jour au plus,
  et sert au lancement suivant. Une nouvelle version de MediaVior fait apparaître un bouton
  **Mettre à jour** en haut de l'appli.
- **Version PC installée par le prompt ou Pinokio** : au lancement (une fois par jour au plus), le
  lanceur récupère la dernière version de MediaVior (`git pull`) et de yt-dlp, en arrière-plan.
  Elles servent au lancement suivant.
- **Version serveur** : voir [SERVEUR.md](SERVEUR.md#mises-à-jour).

La version de yt-dlp utilisée est affichée en bas de la barre latérale.

## Réglages (version PC)

Bouton **Réglages** en haut de l'appli :

- **Dossier des médias** : choisis où arrivent les fichiers téléchargés. Les médias déjà rangés
  peuvent suivre (case cochée par défaut).
- **Lancer MediaVior au démarrage de l'ordinateur** : il démarre en arrière-plan, sans fenêtre.
  Le téléphone et l'extension du navigateur marchent tout de suite.
- Le numéro de version de l'appli est affiché en bas de la fenêtre des réglages et de l'appli.

## Fermer, désinstaller

- **Fermer** : bouton « Quitter MediaVior » en bas de la barre latérale. Fermer la fenêtre seule
  laisse l'appli tourner en fond (un double-clic sur l'icône la rouvre aussitôt).
- **Désinstaller** : supprime l'icône du bureau et le dossier de l'appli (`%LOCALAPPDATA%\MediaVior`
  sur Windows, `~/Library/Application Support/MediaVior` sur macOS, `~/.local/share/mediavior` sur
  Linux si elle a été installée par le prompt), puis `~/.mediavior` (réglages). Tes fichiers restent
  dans `Téléchargements/MediaChest`.
