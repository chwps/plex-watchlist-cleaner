#!/usr/bin/env python3
import os
import json
import secrets
from urllib.parse import urlencode
from flask import Flask, request, render_template_string

app = Flask(__name__)

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
TOKENS_FILE   = "/data/user_tokens.json"
CLIENT_ID     = "plex-watchlist-cleaner"
SCOPE         = "offline_access openid"

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

def build_redirect_uri():
    """
    Construit l'URI de callback à partir des headers de la requête.
    Fonctionne derrière reverse-proxy, NAT, localhost, IP locale, nom DNS...
    """
    # Scheme : http ou https (respecté si derrière reverse-proxy)
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    # Host : IP, nom DNS, port inclus si non 80/443
    host   = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/callback"

def build_auth_url():
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  build_redirect_uri(),
        "scope":         SCOPE,
        "state":         state,
        "forwardUrl":    build_redirect_uri() + "?state=" + state,
        "context[device][product]": "WatchlistCleaner",
        "context[device][platform]": "Web",
        "context[device][device]": "Browser",
        "prompt": "select_account",
    }
    return "https://app.plex.tv/auth/oauth/authorize?" + urlencode(params)

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
        const authUrl = "{{ auth_url }}";
        const w = 600, h = 700;
        const left = (screen.width - w) / 2, top = (screen.height - h) / 2;
        window.open(authUrl, 'PlexOAuth', `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no`);
      }
    </script>
  </body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_INDEX, auth_url=build_auth_url())

@app.route("/callback")
def callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    if not code:
        return "Code manquant", 400

    import requests
    resp = requests.post(
        "https://plex.tv/api/v2/oauth/token",
        data={
            "client_id":     CLIENT_ID,
            "client_secret": "",
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  build_redirect_uri(),
        },
    )
    if not resp.ok:
        return f"Erreur Plex : {resp.text}", 400

    token   = resp.json()["access_token"]
    from plexapi.myplex import MyPlexAccount
    account = MyPlexAccount(token=token)
    username= account.username

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
