# Sécurité

Tu as trouvé une faille ? Merci de ne pas la publier dans une issue.

Utilise **Security → Report a vulnerability** sur la page GitHub du dépôt : le signalement reste
privé jusqu'à sa correction. Décris le problème, comment le reproduire et son impact.

Rappels sur le modèle de sécurité :
- MediaVior n'a pas de comptes ni de mot de passe : il est fait pour tourner sur ton PC
  (`127.0.0.1`) ou sur un réseau de confiance.
- La version PC refuse les requêtes qui ne visent pas `localhost` (DNS rebinding) et les actions
  venant d'autres sites.
- Les liens vers des adresses locales ou internes sont refusés.
