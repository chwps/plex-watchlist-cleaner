# plex-watchlist-cleaner

Application Flask pour nettoyer automatiquement les watchlists Plex d'un serveur multi-utilisateurs. Synchronise les collections du serveur avec les watchlists de tous les utilisateurs, et gère un **système de consensus par notes** pour les demandes de suppression.

## Fonctionnalités

### 🔄 Sync de collections → watchlist
Surveille une ou plusieurs collections Plex. Lorsqu'un média est ajouté à ces collections, il est **automatiquement retiré** de la watchlist de tous les utilisateurs enregistrés.

Idéal en complément de **Maintainerr** : les médias placés dans une collection de sortie ("Leaving soon") par Maintainerr sont nettoyés des watchlists sans avoir besoin de list exclusions.

### ⭐ Consensus par notes (0.5★ / ≥1★)
Un système collaboratif pour gérer les suppressions :

- **Note 0.5★** (= 1/10) → Le média est ajouté à la collection `WEBHOOK_COLLECTION` (demande de suppression)
- **Note ≥ 1★** (= ≥ 2/10) → Le média est **protégé** : s'il est dans `WEBHOOK_COLLECTION`, il en est retiré. Les autres utilisateurs ne peuvent plus le faire supprimer.

Le consensus vérifie **tous les comptes enregistrés** avant de décider — une seule note ≥ 1★ sauve un média.

### 🔔 Notifications Discord
Chaque décision de consensus (suppression ou maintien) est envoyée à un webhook Discord configurable.

### 🌐 Onboarding web (OAuth PIN)
Chaque utilisateur s'autorise simplement en ouvrant `http://<server>:5000` dans son navigateur — pas besoin de partager ses identifiants. Le flow utilise l'authentification **Plex PIN / OAuth** native.

### 🪝 Webhook Plex (`media.rate`)
L'endpoint `/webhook` reçoit les événements de notation de Plex en temps réel et déclenche la vérification de consensus immédiatement (sans attendre le cron).

## Configuration

### Variables d'environnement

| Variable | Requis | Défaut | Description |
|----------|--------|--------|-------------|
| `PLEX_URL` | ✅ | `http://localhost:32400` | URL de ton serveur Plex |
| `ADMIN_USERNAME` | ✅ | — | Nom d'utilisateur Plex de l'admin (pour les opérations serveur) |
| `COLLECTIONS` | ❌ | *(vide)* | Liste de collections à monitorer (séparées par des virgules). Quand un média y est ajouté → retiré des watchlists |
| `WEBHOOK_COLLECTION` | ❌ | `Demande de suppression` | Collection cible pour les médias notés 0.5★ |
| `DISCORD_WEBHOOK_URL` | ❌ | *(vide)* | URL du webhook Discord pour les notifications |
| `CRON_SCHEDULE` | ❌ | `0 */1 * * *` | Expression cron pour la sync automatique (par défaut : chaque heure) |
| `RUN_SYNC_AT_STARTUP` | ❌ | `false` | Lancer une sync au démarrage (`true` / `false`) |
| `TOKEN_TTL_HOURS` | ❌ | `24` | Durée de vie du cache du token admin (heures) |
| `APP_NAME` | ❌ | `Plex Watchlist Cleaner` | Nom affiché lors de l'authentification Plex |

### Docker Compose

```yaml
services:
  plex-watchlist-cleaner:
    image: ghcr.io/chwps/plex-watchlist-cleaner:latest
    container_name: plex-watchlist-cleaner
    restart: unless-stopped
    environment:
      PLEX_URL: "http://plex:32400"
      ADMIN_USERNAME: "ton_compte_admin"
      COLLECTIONS: "Leaving soon,Cleaned"
      WEBHOOK_COLLECTION: "Demande de suppression"
      DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/..."
      CRON_SCHEDULE: "0 */1 * * *"
      RUN_SYNC_AT_STARTUP: "true"
    volumes:
      - ./data:/data
    ports:
      - "5000:5000"
```

## Utilisation

### 1. Autoriser les utilisateurs (une seule fois)

Chaque utilisateur ouvre **`http://<serveur>:5000`** dans son navigateur :
1. Cliquer sur **"Choisir un compte Plex"**
2. Se connecter à son compte Plex et autoriser l'application
3. Le token est sauvegardé automatiquement dans `/data/user_tokens.json`
4. Fermer la fenêtre — c'est tout !

### 2. Configurer le webhook Plex (optionnel, recommandé)

Dans ton serveur Plex : **Réglages → Web & XML → Ajouter un nouveau webhook**
- URL : `http://plex-watchlist-cleaner:5000/webhook`
- Événement : cocher **`media.rate`**

Les notes sont traitées en temps réel dès qu'un utilisateur note un média.

### 3. Sync automatique

La sync s'exécute automatiquement selon le cron configuré. Tu peux aussi la déclencher manuellement :

```bash
curl -X POST http://localhost:5000/run_sync
```

### Système de notes en détail

| Note Plex | Valeur API | Effet |
|-----------|-----------|-------|
| 0.5★ | `1.0` | Demande de suppression → ajout à `WEBHOOK_COLLECTION` |
| 1.0★ | `2.0` | Protection → retrait de `WEBHOOK_COLLECTION` |
| ≥ 1.0★ | ≥ `2.0` | Protection |

**Règle de consensus** : si un média a au moins une note ≥ 1★, il est protégé et ne peut plus être supprimé par un 0.5★.

## Architecture

```
┌─────────────────────┐
│   Interface Web     │  :5000     ┌──────────────────────────┐
│   (OAuth PIN)       │ ◄──────────│   Plex Web               │
│                     │            │   (authentification)     │
├─────────────────────┤            └──────────────────────────┘
│  Flask App          │
│                     │         ┌──────────────────────────┐
│  / (onboarding)     │         │                          │
│  /login + /callback │         │   Plex Server            │
│                     │ ◄─────► │   (Collections, Ratings) │
│  /run_sync          │         │                          │
│  /webhook           │ ◄─────► │                          │
├─────────────────────┤         └──────────────────────────┘
│                     │
│  sync_collections   │         ┌──────────────────────────┐
│  _once()            │ ──────► │   Discord Webhook        │
│                     │         │   (notifications)        │
├─────────────────────┤         └──────────────────────────┘
│                     │
│  Cron (entrypoint)  │
└─────────────────────┘
```

## Structure des données

```
data/
├── user_tokens.json      # Tokens OAuth de chaque utilisateur
├── plex_token.json       # Cache du token admin
├── plex_watchlist_state.json  # État des collections déjà traitées
└── client_id.txt         # ID client Plex (généré automatiquement)
```

## CI/CD

Build & push automatique sur **GitHub Container Registry** via GitHub Actions :
- Branche `main` → tag `latest`
- Branche `dev` → tag `dev`

## Notes importantes

- **Ajout d'un nouvel utilisateur** : si tu ajoutes un utilisateur après la première sync, il est recommandé de supprimer le fichier `data/plex_watchlist_state.json` pour qu'il hérite du nettoyage des médias déjà présents dans les collections monitorées.
- Le compte **admin** doit aussi passer par l'onboarding web pour fournir son token (il sera utilisé pour les opérations serveur : lecture des collections, modifications, etc.).
