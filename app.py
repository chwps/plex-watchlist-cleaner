#!/usr/bin/env python3
"""
App combinée :
 - web onboarding Plex (PIN / Auth App)
 - stockage tokens utilisateurs (/data/user_tokens.json)
 - si l'utilisateur connecté est l'admin (ADMIN_USERNAME), on met aussi à jour /data/plex_token.json
 - routine de sync des collections (fonction sync_collections_once)
"""

import os
import json
import time
import secrets
import logging
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

# TTL config (env: TOKEN_TTL_HOURS) default 24 hours
TOKEN_TTL = int(os.getenv("TOKEN_TTL_HOURS", "24")) * 3600

# Admin account name if you want to auto-detect ("Tristan.Brn")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")  # si défini, on considérera ce compte comme admin
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
COLLECTIONS = [c.strip() for c in os.getenv("COLLECTIONS", "").split(",") if c.strip()]

# ------------------------------------------------------------------
# UTILS stockage / client id
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

# user tokens helpers
def load_user_tokens():
    return load_json(TOKENS_FILE) or {}

def save_user_token(username, token):
    tokens = load_user_tokens()
    tokens[username] = token
    save_json(TOKENS_FILE, tokens)
    logging.info("Token utilisateur enregistré pour %s", username)

# admin token helpers (cached token used to access PlexServer)
def cache_admin_token(token):
    save_json(TOKEN_FILE, {"token": token, "ts": time.time()})
    logging.info("Token admin mis en cache")

def get_admin_token():
    # 1) vérifier cache TOKEN_FILE
    d = load_json(TOKEN_FILE)
    if d.get("token") and d.get("ts") and (time.time() - d["ts"] < TOKEN_TTL):
        logging.info("Token admin récupéré depuis le cache.")
        return d["token"]

    # 2) si ADMIN_USERNAME est défini, vérifier si on a le token dans user_tokens.json
    if ADMIN_USERNAME:
        tokens = load_user_tokens()
        admin_token = tokens.get(ADMIN_USERNAME)
        if admin_token:
            logging.info("Token admin récupéré depuis user_tokens.json (admin connecté via onboarding).")
            # on met en cache pour accélérer les lectures suivantes
            cache_admin_token(admin_token)
            return admin_token

    # 3) pas de token admin disponible
    logging.warning("Aucun token admin disponible en cache ni dans user_tokens.json.")
    return None

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
    """Crée un PIN et redirige l'utilisateur vers Plex Auth App"""
    client_id = get_client_id()

    resp = requests.post(
        f"{PLEX_API}/pins",
        headers={"accept": "application/json"},
        data={
            "strong": "true",
            "X-Plex-Product": APP_NAME,
            "X-Plex-Client-Identifier": client_id,
        },
        timeout=10,
    )
    if not resp.ok:
        return f"Erreur création PIN : {resp.status_code} {resp.text}", 400

    pin = resp.json()
    pin_id = pin["id"]
    pin_code = pin["code"]

    # forwardUrl: callback avec pin info (on utilisera ces params pour vérifier)
    forward_url = build_redirect_uri() + f"?pin_id={pin_id}&pin_code={pin_code}"
    params = {
        "clientID": client_id,
        "code": pin_code,
        "forwardUrl": forward_url,
        "context[device][product]": APP_NAME,
    }
    auth_url = "https://app.plex.tv/auth#?" + urlencode(params)
    return redirect(auth_url)

@app.route("/callback")
def callback():
    """Page de retour de Plex après authent"""
    pin_id   = request.args.get("pin_id")
    pin_code = request.args.get("pin_code")
    if not pin_id or not pin_code:
        return "Paramètres manquants", 400

    client_id = get_client_id()
    resp = requests.get(
        f"{PLEX_API}/pins/{pin_id}",
        headers={"accept": "application/json"},
        data={
            "code": pin_code,
            "X-Plex-Client-Identifier": client_id,
        },
        timeout=10,
    )
    if not resp.ok:
        return f"Erreur check PIN : {resp.status_code} {resp.text}", 400

    data = resp.json()
    token = data.get("authToken")
    if not token:
        return "Authentification non terminée. Veuillez réessayer après avoir cliqué sur 'Authorize'.", 400

    # récupérer username via l'API user pour connaître le nom du compte
    user_resp = requests.get(
        f"{PLEX_API}/user",
        headers={
            "accept": "application/json",
            "X-Plex-Product": APP_NAME,
            "X-Plex-Client-Identifier": client_id,
            "X-Plex-Token": token,
        },
        timeout=10,
    )
    if not user_resp.ok:
        logging.warning("Impossible de récupérer infos user après connexion : %s", user_resp.text)
        username = "unknown"
    else:
        username = user_resp.json().get("username", "unknown")

    # enregister token utilisateur (remplace si existant -> évite doublons)
    save_user_token(username, token)

    # si c'est le compte admin configuré, on met aussi à jour le cache admin
    if ADMIN_USERNAME and username == ADMIN_USERNAME:
        cache_admin_token(token)
        logging.info("Compte admin connecté via la page web. Token admin mis à jour.")

    return f"""
    <h2>Merci {username} !</h2>
    <p>Le token a été enregistré. Vous pouvez fermer cette fenêtre.</p>
    <script>window.close();</script>
    """

# ------------------------------------------------------------------
# LOGIQUE de sync (identique à ton code mais réutilisable ici)
# ------------------------------------------------------------------
def list_all_users():
    tokens = load_user_tokens()
    if not tokens:
        logging.warning("Aucun token utilisateur enregistré.")
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
            logging.exception("Erreur pour %s : %s", user["username"], e)

def sync_collections_once():
    if not COLLECTIONS:
        logging.warning("Aucune collection configurée (env COLLECTIONS).")
        return

    logging.info("Collections à surveiller : %s", ", ".join(COLLECTIONS))

    token = get_admin_token()
    if not token:
        logging.error("Pas de token admin disponible — impossible de se connecter au serveur Plex local.")
        return

    server = PlexServer(PLEX_URL, token=token)
    logging.info("Connecté au serveur Plex local.")

    current = set()
    for name in COLLECTIONS:
        found = False
        for lib in server.library.sections():
            if lib.type not in {"movie", "show"}:
                continue
            try:
                coll = next(c for c in lib.collections() if c.title == name)
                nb_items = len(coll.items())
                logging.info("Collection '%s' trouvée dans %s (%d élément(s))", name, lib.title, nb_items)
                current.update(item.guid for item in coll.items())
                found = True
                break
            except StopIteration:
                logging.debug("Collection '%s' absente de la bibliothèque %s", name, lib.title)
        if not found:
            logging.warning("Collection '%s' introuvable dans toutes les bibliothèques.", name)

    previous = set(load_json(STATE_FILE) or [])
    new_guids = current - previous

    logging.info("GUID présents dans les collections : %d", len(current))
    logging.info("GUID déjà connus : %d", len(previous))
    logging.info("Nouveaux GUID à retirer : %d", len(new_guids))

    if new_guids:
        remove_batch(new_guids)
    else:
        logging.info("Rien à retirer, watchlist déjà synchronisée.")

    save_json(STATE_FILE, list(current))
    logging.info("État sauvegardé dans %s", STATE_FILE)

# Expose un endpoint pour déclencher manuellement (utile pour debug/cron)
# **ATTENTION** : si exposé en prod, protège cet endpoint (token, IP, etc.)
@app.route("/run_sync", methods=["POST"])
def run_sync_endpoint():
    # Optional: vérifier header X-Admin-Token ou IP whitelist
    # Ici on exécute synchro et retourne OK
    try:
        sync_collections_once()
        return "ok", 200
    except Exception as e:
        logging.exception("Erreur lors du run_sync")
        return f"error: {e}", 500

# ------------------------------------------------------------------
# DÉMARRAGE
# ------------------------------------------------------------------
if __name__ == "__main__":
    logging.info("==== Démarrage combiné plex-watchlist-cleaner (web + sync) ====")
    # Ne lance pas sync automatiquement ici — laisse le scheduler (cron) le faire,
    # ou utilise /run_sync pour déclenchement manuel.
    if os.getenv("RUN_SYNC_AT_STARTUP", "false").lower() in {"1", "true", "yes"}:
        logging.info("Lancement initial de la synchro car RUN_SYNC_AT_STARTUP est activé.")
        sync_collections_once()

    # Lancer le serveur Flask (il servira la page d'onboarding)
    app.run(host="0.0.0.0", port=5000, debug=False)
