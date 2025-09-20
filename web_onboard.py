#!/usr/bin/env python3
import os
import json
import secrets
from flask import Flask, request, redirect, jsonify
from plexapi.myplex import MyPlexAccount

TOKENS_FILE = "/data/user_tokens.json"
CLIENT_ID   = "plex-watchlist-cleaner"   # quelconque mais fixe
REDIRECT_URI= "http://TON_NAS_IP:5000/callback"  # à adapter

app = Flask(__name__)

def load_tokens():
    if os.path.exists(TOKENS_FILE):
        return json.load(open(TOKENS_FILE))
    return {}

def save_tokens(tokens):
    json.dump(tokens, open(TOKENS_FILE, "w"))

@app.route("/")
def index():
    return """
    <h1>Plex Watchlist Cleaner</h1>
    <p>Cliquez ci-dessous pour autoriser l'accès à votre watchlist.</p>
    <a href="/login"><button>Se connecter avec Plex</button></a>
    """

@app.route("/login")
def login():
    state = secrets.token_urlsafe(16)
    url = (
        "https://app.plex.tv/auth/#!"
        f"?clientID={CLIENT_ID}"
        f"&codeChallenge=&context[device][product]=WatchlistCleaner"
        f"&context[device][platform]=Web"
        f"&forwardUrl={REDIRECT_URI}?state={state}"
    )
    return redirect(url)

@app.route("/callback")
def callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    if not code:
        return "Code manquant", 400

    # Échange code contre token
    account = MyPlexAccount.exchange_code(code, CLIENT_ID, REDIRECT_URI)
    token   = account.authenticationToken
    username= account.username

    tokens = load_tokens()
    tokens[username] = token
    save_tokens(tokens)

    return f"""
    <h2>Merci {username} !</h2>
    <p>Le token a été enregistré. Vous pouvez fermer cette fenêtre.</p>
    """
