#!/usr/bin/env python3
import os
import json
import secrets
import requests
from urllib.parse import urlencode
from flask import Flask, request, render_template_string, redirect

app = Flask(__name__)

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
TOKENS_FILE   = "/data/user_tokens.json"
APP_NAME      = "Plex Watchlist Cleaner"
CLIENT_ID_FILE= "/data/client_id.txt"
PLEX_API      = "https://plex.tv/api/v2"

# ------------------------------------------------------------------
# UTILS
# ------------------------------------------------------------------
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        return json.load(open(TOKENS_FILE))
    return {}

def save_tokens(tokens):
    os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
    json.dump(tokens, open(TOKENS_FILE, "w"), indent=2)

def get_client_id():
    """Génère ou récupère le client_id unique de l'app."""
    if os.path.exists(CLIENT_ID_FILE):
        return open(CLIENT_ID_FILE).read().strip()
    cid = secrets.token_hex(16)
    os.makedirs(os.path.dirname(CLIENT_ID_FILE), exist_ok=True)
    open(CLIENT_ID_FILE, "w").write(cid)
    return cid

def build_redirect_uri():
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host   = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/callback"

# ------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------
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
    )
    if not resp.ok:
        return f"Erreur PIN : {resp.text}", 400

    pin = resp.json()
    pin_id = pin["id"]
    pin_code = pin["code"]

    # stocker id en session (ici simplifié, pourrait être DB / redis etc.)
    request.environ["pin_id"] = pin_id
    request.environ["pin_code"] = pin_code

    params = {
        "clientID": client_id,
        "code": pin_code,
        "forwardUrl": build_redirect_uri() + f"?pin_id={pin_id}&pin_code={pin_code}",
        "context[device][product]": APP_NAME,
    }
    auth_url = "https://app.plex.tv/auth#?" + urlencode(params)

    return redirect(auth_url)

@app.route("/callback")
def callback():
    """Appelé par Plex après login"""
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
    )
    if not resp.ok:
        return f"Erreur PIN check : {resp.text}", 400

    data = resp.json()
    token = data.get("authToken")
    if not token:
        return "Authentification non terminée. Veuillez réessayer.", 400

    # Récupérer infos user
    user_resp = requests.get(
        f"{PLEX_API}/user",
        headers={
            "accept": "application/json",
            "X-Plex-Product": APP_NAME,
            "X-Plex-Client-Identifier": client_id,
            "X-Plex-Token": token,
        },
    )
    if not user_resp.ok:
        return f"Impossible de récupérer l'utilisateur : {user_resp.text}", 400

    username = user_resp.json().get("username", "inconnu")

    tokens = load_tokens()
    tokens[username] = token
    save_tokens(tokens)

    return f"""
    <h2>Merci {username} !</h2>
    <p>Le token a été enregistré. Vous pouvez fermer cette fenêtre.</p>
    <script>window.close();</script>
    """

# ------------------------------------------------------------------
# DÉMARRAGE
# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
