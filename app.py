#!/usr/bin/env python3
"""
App combinée :
 - web onboarding Plex (PIN / Auth App)
 - stockage tokens utilisateurs (/data/user_tokens.json)
 - si l'utilisateur connecté est l'admin (ADMIN_USERNAME), on met aussi à jour /data/plex_token.json
 - routine de sync des collections (fonction sync_collections_once)
 - Logique de consensus (une note > 0.5 annule la suppression)
"""

import os
import json
import time
import secrets
import logging
import threading
from urllib.parse import urlencode

import requests
from flask import Flask, request, render_template_string, redirect

from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

APP_NAME       = os.getenv("APP_NAME", "Plex Watchlist Cleaner")
TOKENS_FILE    = os.getenv("TOKENS_FILE", "/data/user_tokens.json")
TOKEN_FILE     = os.getenv("TOKEN_FILE", "/data/plex_token.json")  # admin token cache
STATE_FILE     = os.getenv("STATE_FILE", "/data/plex_watchlist_state.json")
CLIENT_ID_FILE = os.getenv("CLIENT_ID_FILE", "/data/client_id.txt")
PLEX_API       = "https://plex.tv/api/v2"

TOKEN_TTL = int(os.getenv("TOKEN_TTL_HOURS", "24")) * 3600
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
COLLECTIONS = [c.strip() for c in os.getenv("COLLECTIONS", "").split(",") if c.strip()]
WEBHOOK_COLLECTION = os.getenv("WEBHOOK_COLLECTION", "Demande de suppression")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ------------------------------------------------------------------
# UTILS
# ------------------------------------------------------------------
def load_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            logging.exception("Impossible de lire %s", path)
    return {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w"), indent=2)

def get_client_id():
    if os.path.exists(CLIENT_ID_FILE):
        return open(CLIENT_ID_FILE).read().strip()
    cid = secrets.token_hex(16)
    os.makedirs(os.path.dirname(CLIENT_ID_FILE), exist_ok=True)
    open(CLIENT_ID_FILE, "w").write(cid)
    return cid

def load_user_tokens():
    return load_json(TOKENS_FILE) or {}

def save_user_token(username, token):
    tokens = load_user_tokens()
    tokens[username] = token
    save_json(TOKENS_FILE, tokens)
    logging.info("Token utilisateur enregistré pour %s", username)

def cache_admin_token(token):
    save_json(TOKEN_FILE, {"token": token, "ts": time.time()})
    logging.info("Token admin mis en cache")

def get_admin_token():
    d = load_json(TOKEN_FILE)
    if d.get("token") and d.get("ts") and (time.time() - d["ts"] < TOKEN_TTL):
        return d["token"]
    if ADMIN_USERNAME:
        tokens = load_user_tokens()
        admin_token = tokens.get(ADMIN_USERNAME)
        if admin_token:
            cache_admin_token(admin_token)
            return admin_token
    return None

def send_to_discord(message):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=5)
        except Exception as e:
            logging.error("Erreur Discord : %s", e)

# ------------------------------------------------------------------
# PIN / Auth App flow (onboarding web)
# ------------------------------------------------------------------
def build_redirect_uri():
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host   = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/callback"

HTML_INDEX = """\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Plex Watchlist Cleaner</title>
    <style>
      body{font-family:Arial,Helvetica,sans-serif;background:#0d0d0d;color:#fff;text-align:center;padding-top:10%}
      h1{margin-bottom:1rem}.btn{background:#e5a00d;border:0;padding:14px 28px;font-size:16px;border-radius:4px;cursor:pointer}.btn:hover{background:#ffc107}
    </style>
  </head>
  <body>
    <h1>Autoriser l’accès à votre watchlist</h1>
    <p>Connectez-vous pour autoriser l'application à gérer votre watchlist.</p>
    <button class="btn" onclick="openPlex()">Choisir un compte Plex</button>

    <script>
      function openPlex() {
        window.location.href = "/login";
      }
    </script>
  </body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_INDEX)

@app.route("/login")
def login():
    client_id = get_client_id()
    resp = requests.post(
        f"{PLEX_API}/pins",
        headers={"accept": "application/json"},
        data={"strong": "true", "X-Plex-Product": APP_NAME, "X-Plex-Client-Identifier": client_id},
        timeout=10,
    )
    if not resp.ok:
        return f"Erreur création PIN : {resp.status_code} {resp.text}", 400

    pin = resp.json()
    forward_url = build_redirect_uri() + f"?pin_id={pin['id']}&pin_code={pin['code']}"
    params = {"clientID": client_id, "code": pin['code'], "forwardUrl": forward_url, "context[device][product]": APP_NAME}
    auth_url = "https://app.plex.tv/auth#?" + urlencode(params)
    return redirect(auth_url)

@app.route("/callback")
def callback():
    pin_id   = request.args.get("pin_id")
    pin_code = request.args.get("pin_code")
    if not pin_id or not pin_code:
        return "Paramètres manquants", 400

    client_id = get_client_id()
    resp = requests.get(
        f"{PLEX_API}/pins/{pin_id}",
        headers={"accept": "application/json"},
        data={"code": pin_code, "X-Plex-Client-Identifier": client_id},
        timeout=10,
    )
    if not resp.ok:
        return f"Erreur check PIN : {resp.status_code} {resp.text}", 400

    data = resp.json()
    token = data.get("authToken")
    if not token:
        return "Authentification non terminée.", 400

    user_resp = requests.get(
        f"{PLEX_API}/user",
        headers={"accept": "application/json", "X-Plex-Product": APP_NAME, "X-Plex-Client-Identifier": client_id, "X-Plex-Token": token},
        timeout=10,
    )
    username = user_resp.json().get("username", "unknown") if user_resp.ok else "unknown"

    save_user_token(username, token)
    if ADMIN_USERNAME and username == ADMIN_USERNAME:
        cache_admin_token(token)

    return f"<h2>Merci {username} !</h2><p>Le token a été enregistré. Vous pouvez fermer cette fenêtre.</p><script>window.close();</script>"

# ------------------------------------------------------------------
# LOGIQUE de sync
# ------------------------------------------------------------------
def list_all_users():
    tokens = load_user_tokens()
    return [{"username": u, "token": t} for u, t in tokens.items()]

def remove_batch(guids):
    for user in list_all_users():
        try:
            acc = MyPlexAccount(token=user["token"])
            watchlist = {item.guid: item for item in acc.watchlist()}
            for g in guids:
                if g in watchlist:
                    acc.removeFromWatchlist(watchlist[g])
                    logging.info("Retiré %s pour %s", watchlist[g].title, user["username"])
        except Exception as e:
            logging.error("Erreur pour %s : %s", user["username"], e)

def sync_ratings():
    """Vérifie les notes, agrège les données, et applique un consensus global"""
    logging.info("Démarrage de la vérification des notes (Polling avec Consensus)...")
    
    admin_token = get_admin_token()
    if not admin_token: return
    users = list_all_users()
    if not users: return

    try:
        admin_server = PlexServer(PLEX_URL, token=admin_token)
        server_name = admin_server.friendlyName
    except Exception as e:
        logging.error("Erreur connexion admin : %s", e)
        return

    # Dictionnaire mémoire pour agréger les notes de tout le monde avant d'agir
    media_state = {}

    for u in users:
        username = u["username"]
        token = u["token"]
        try:
            if token == admin_token:
                user_server = admin_server
            else:
                account = MyPlexAccount(token=token)
                user_server = account.resource(server_name).connect()

            for section in user_server.library.sections():
                if section.type not in {"movie", "show"}: continue

                try:
                    # On identifie les demandes de suppression (0.5 étoile = 1.0)
                    bad_items = section.search(userRating=1.0)
                    # On identifie TOUT média protégé (plus de 0.5 étoile = >1.0)
                    protected_items = section.search(userRating__gt=1.0)

                    for item in bad_items:
                        rk = item.ratingKey
                        if rk not in media_state: media_state[rk] = {'title': item.title, 'is_bad': False, 'bad_users': [], 'is_protected': False, 'protectors': []}
                        media_state[rk]['is_bad'] = True
                        media_state[rk]['bad_users'].append(username)

                    for item in protected_items:
                        rk = item.ratingKey
                        if rk not in media_state: media_state[rk] = {'title': item.title, 'is_bad': False, 'bad_users': [], 'is_protected': False, 'protectors': []}
                        media_state[rk]['is_protected'] = True
                        media_state[rk]['protectors'].append(f"{username} ({float(item.userRating)/2}/5)")

                except Exception:
                    pass
        except Exception as e:
            logging.error("Erreur générale pour %s : %s", username, e)

    # Une fois qu'on a l'avis de tout le monde, on prend les décisions
    for rk, state in media_state.items():
        try:
            admin_item = admin_server.fetchItem(int(rk))
            current_collections = [c.tag for c in admin_item.collections]

            if state['is_protected']:
                # Le média est sauvé par au moins une personne
                if WEBHOOK_COLLECTION in current_collections:
                    logging.info("Consensus : Retrait de '%s' car protégé par %s", state['title'], state['protectors'])
                    admin_item.removeCollection(WEBHOOK_COLLECTION)
                    send_to_discord(f"🛡️ **Maintien sur le serveur** : La suppression de **{state['title']}** a été annulée grâce aux notes de : {', '.join(state['protectors'])}")
            
            elif state['is_bad']:
                # Uniquement des notes de 0.5, aucune protection
                if WEBHOOK_COLLECTION not in current_collections:
                    logging.info("Consensus : Ajout de '%s' (noté 0.5 par %s)", state['title'], state['bad_users'])
                    admin_item.addCollection(WEBHOOK_COLLECTION)
                    send_to_discord(f"🗑️ **Demande de suppression** validée pour **{state['title']}** (noté 0.5 par {', '.join(state['bad_users'])})")

        except Exception as e:
            logging.error("Erreur lors de l'application du consensus pour %s : %s", rk, e)

def sync_collections_once():
    sync_ratings()

    if not COLLECTIONS: return

    token = get_admin_token()
    if not token: return
    server = PlexServer(PLEX_URL, token=token)

    current = set()
    for name in COLLECTIONS:
        for lib in server.library.sections():
            if lib.type not in {"movie", "show"}: continue
            try:
                coll = next(c for c in lib.collections() if c.title == name)
                current.update(item.guid for item in coll.items())
                break
            except StopIteration:
                pass

    previous = set(load_json(STATE_FILE) or [])
    new_guids = current - previous

    if new_guids:
        remove_batch(new_guids)

    save_json(STATE_FILE, list(current))

# ------------------------------------------------------------------
# THREAD WEBHOOK (Arrière-plan)
# ------------------------------------------------------------------
def process_webhook_rating(rating_val, rating_key, title, username):
    """Vérifie le consensus en arrière-plan suite à un webhook pour ne pas bloquer Plex"""
    logging.info("Webhook reçu pour '%s'. Vérification globale...", title)
    
    admin_token = get_admin_token()
    if not admin_token: return
    try:
        admin_server = PlexServer(PLEX_URL, token=admin_token)
        server_name = admin_server.friendlyName
    except Exception: return

    is_protected = False
    protectors = []

    # On interroge les autres utilisateurs
    for u in list_all_users():
        try:
            if u["token"] == admin_token:
                user_server = admin_server
            else:
                account = MyPlexAccount(token=u["token"])
                user_server = account.resource(server_name).connect()

            item = user_server.fetchItem(int(rating_key))
            if item.userRating is not None and float(item.userRating) > 1.0:
                is_protected = True
                protectors.append(f"{u['username']} ({float(item.userRating)/2}/5)")
        except Exception:
            pass

    # Application de la décision
    try:
        admin_item = admin_server.fetchItem(int(rating_key))
        current_collections = [c.tag for c in admin_item.collections]

        if is_protected:
            if WEBHOOK_COLLECTION in current_collections:
                admin_item.removeCollection(WEBHOOK_COLLECTION)
                send_to_discord(f"🛡️ **Maintien sur le serveur** : La suppression de **{title}** est bloquée/annulée grâce aux notes de : {', '.join(protectors)}")
            elif rating_val == 1.0:
                logging.info("Webhook : %s a noté 0.5, mais '%s' est protégé par %s. Ignoré.", username, title, protectors)
        else:
            if rating_val == 1.0 and WEBHOOK_COLLECTION not in current_collections:
                admin_item.addCollection(WEBHOOK_COLLECTION)
                send_to_discord(f"🗑️ **Demande de suppression** via Webhook reçue par {username} pour : **{title}**")
                
    except Exception as e:
        logging.error("Erreur Thread Webhook : %s", e)

# ------------------------------------------------------------------
# ROUTES API
# ------------------------------------------------------------------
@app.route("/run_sync", methods=["POST"])
def run_sync_endpoint():
    try:
        sync_collections_once()
        return "ok", 200
    except Exception as e:
        return f"error: {e}", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    payload_str = request.form.get('payload')
    data = json.loads(payload_str) if payload_str else (request.get_json(silent=True) or {})

    if data.get('event') == 'media.rate':
        rating = data.get('rating') or data.get('Metadata', {}).get('userRating')
        username = data.get('Account', {}).get('title', 'Inconnu')
        
        try:
            rating_val = float(rating) if rating is not None else None
        except ValueError:
            rating_val = None

        if rating_val is not None:
            metadata_obj = data.get('Metadata', {})
            rating_key = metadata_obj.get('ratingKey')
            title = metadata_obj.get('title', 'Titre inconnu')
            
            # On lance le travail de vérification en arrière-plan (Thread)
            # pour renvoyer tout de suite "202 Accepted" à Plex et éviter un Timeout
            threading.Thread(target=process_webhook_rating, args=(rating_val, rating_key, title, username)).start()
            return "Vérification de la note en arrière-plan", 202

    return "Événement ignoré", 200

# ------------------------------------------------------------------
# DÉMARRAGE
# ------------------------------------------------------------------
if __name__ == "__main__":
    logging.info("==== Démarrage combiné plex-watchlist-cleaner ====")
    if os.getenv("RUN_SYNC_AT_STARTUP", "false").lower() in {"1", "true", "yes"}:
        sync_collections_once()

    app.run(host="0.0.0.0", port=5000, debug=False)