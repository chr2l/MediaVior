# Contribuer à MediaVior

Merci de ton intérêt ! Toutes les contributions sont bienvenues : bug signalé, idée, correction de
texte, code.

## Signaler un bug ou proposer une idée

Ouvre une [issue](https://github.com/chr2l/MediaVior/issues) en expliquant :
- ce que tu as fait (le site concerné, sans forcément donner le lien exact) ;
- ce qui s'est passé, et ce que tu attendais ;
- ton système (Windows, macOS, Linux, serveur Docker) et la version de yt-dlp (en bas de l'appli).

Beaucoup d'échecs viennent d'un site qui a changé : essaie d'abord de mettre yt-dlp à jour
(relancer l'appli suffit en général).

## Proposer une modification

1. Lis [docs/DEVELOPPEMENT.md](docs/DEVELOPPEMENT.md) pour la carte du code.
2. Crée une branche depuis `dev`, fais des changements ciblés, puis ouvre une pull request vers `dev`.
3. Dans la description : le problème, ce qui change pour l'utilisateur, et comment tu l'as testé.

Quelques règles du projet :
- Interface et messages en français simple, phrases courtes.
- Pas de nouvelle dépendance sans bonne raison ; pas de framework front.
- Rien qui envoie des données à un tiers sans que l'utilisateur le sache.
- Ne fige pas yt-dlp.

En contribuant, tu acceptes que ton code soit publié sous la [licence MIT](LICENSE) du projet.
