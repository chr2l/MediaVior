# Relais MediaVior (téléphone ↔ PC)

Petit programme qui relie l'appli PC et le téléphone, comme WhatsApp Web. Il tourne sur
**Cloudflare Workers**, dans l'offre gratuite. Il sert aussi la page du téléphone (`public/`),
installable sur l'écran d'accueil.

```
téléphone ──(messages chiffrés)──► relais (Cloudflare) ◄──(connexion gardée ouverte)── PC
téléphone ◄═══════════════ fichier, en direct (WebRTC) ═══════════════════════════════ PC
```

## Ce que voit le relais

- Il garde, pour chaque paire PC + téléphones, des **empreintes** (SHA-256) des codes d'accès. Rien
  d'autre : ni liens, ni titres, ni fichiers.
- Les messages sont chiffrés de bout en bout (AES-GCM). La clé est dans le QR code et ne lui est
  jamais envoyée.
- Les fichiers vont directement du PC au téléphone. Sur certains réseaux, la connexion directe est
  impossible : le fichier reste sur le PC. On peut ajouter un relais de fichiers (TURN, voir plus
  bas), mais il n'est pas activé par défaut.

## Ce que ça coûte

Rien, dans l'offre gratuite de Cloudflare (Workers Free). Les connexions en veille ne comptent pas
(« hibernation »), et le maintien de connexion (ping) est répondu sans réveiller le relais.

Limites gratuites utiles (novembre 2026) : 100 000 requêtes par jour (un message de WebSocket
compte pour 1/20 de requête), 13 000 Go-s de calcul par jour pour les Durable Objects. Une
journée normale (un PC, un téléphone, une dizaine de liens) en utilise quelques dizaines. Si la
limite est atteinte, le relais refuse les nouvelles connexions jusqu'à minuit (UTC), sans frais :
l'offre gratuite ne facture jamais de dépassement.

Protections : 30 connexions par minute et par adresse IP, 120 messages par minute par téléphone,
8 téléphones par PC, messages de 64 Ko au plus, QR code valable 10 minutes et une seule fois.

## Mettre en ligne ou mettre à jour

**Automatique** : `.github/workflows/relais.yml` met le relais en ligne à chaque mise en ligne
(`main`) qui touche ce dossier, ou à la main depuis l'onglet **Actions** → **Relais téléphone** →
**Run workflow**. Il lui faut deux secrets GitHub (**Settings → Secrets and variables → Actions**) :

- `CLOUDFLARE_API_TOKEN` : Cloudflare → **Mon profil → Jetons d'API → Créer un jeton** → modèle
  **Modifier les Cloudflare Workers** (compte et zone du domaine du relais) ;
- `CLOUDFLARE_ACCOUNT_ID` : l'identifiant du compte, affiché à droite de la page d'accueil de
  **Workers et Pages**.

**À la main**, depuis ce dossier, avec Node.js :

```bash
npm install
npx wrangler login     # une fois : ouvre Cloudflare dans le navigateur
npx wrangler deploy
```

L'adresse publique est dans `wrangler.jsonc` (`routes`). Elle doit correspondre à `RELAIS` dans
[`app/jumelage.py`](../app/jumelage.py). Pour utiliser ton propre relais sans modifier le code :
variable d'environnement `MEDIAVIOR_RELAIS=https://ton-relais.exemple` avant de lancer MediaVior.

Essai en local : `npx wrangler dev`, puis `MEDIAVIOR_RELAIS=http://127.0.0.1:8787` pour l'appli PC.

## Relais de fichiers (TURN), facultatif

Pour les réseaux où la connexion directe échoue, Cloudflare propose un relais de fichiers (TURN) :
1 000 Go gratuits par mois, puis 0,05 $ par Go (il faut alors une carte bancaire sur le compte).
Pour l'activer : Cloudflare → **Realtime** → **TURN Server** → créer une clé, puis

```bash
npx wrangler secret put TURN_KEY_ID
npx wrangler secret put TURN_KEY_API_TOKEN
```

Sans ces deux secrets, le relais n'utilise que STUN (gratuit et illimité).
