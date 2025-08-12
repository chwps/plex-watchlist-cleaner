#!/usr/bin/env python3
import os
import json
import logging
import time
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

STATE_FILE = "/data/plex_watchlist_state.json"
TOKEN_FILE = "/data/plex_token.json"
TOKEN_TTL  = 3600 * 24

# ----------  utilitaires ----------
def get_admin_token():
    if os.path.exists(TOKEN_FILE):
        data = json.load(open(TOKEN_FILE))
        if time.time() - data["ts"] < TOKEN_TTL:
            logging.info("Token admin récupéré depuis le cache.")
            return data["token"]
    logging.info("Connexion Plex admin pour obtenir le token…")
    acc   = MyPlexAccount(os.getenv("PLEX_USERNAME"), os.getenv("PLEX_PASSWORD"))
    token = acc.authenticationToken
    json.dump({"token": token, "ts": time.time()}, open(TOKEN_FILE, "w"))
    logging.info("Token admin obtenu et mis en cache.")
    return token

def list_all_users():
    users = [{"username": os.getenv("PLEX_USERNAME"), "token": get_admin_token()}]
    extra = os.getenv("PLEX_EXTRA_USERS", "")
    for pair in extra.split(","):
        if ":" in pair:
            u, p = pair.split(":", 1)
            logging.info("Connexion de l’ami %s…", u.strip())
            acc = MyPlexAccount(u.strip(), p.strip())
            users.append({"username": u.strip(), "token": acc.authenticationToken})
    logging.info("%d utilisateur(s) seront traités.", len(users))
    return users

# ----------  logique ----------
def remove_batch(guids):
    if not guids:
        return
    logging.info("Début retrait de %d GUID(s) des watchlists…", len(guids))
    for user in list_all_users():
        try:
            acc = MyPlexAccount(token=user["token"])
            watchlist = {item.guid: item for item in acc.watchlist()}
            removed = 0
            for g in guids:
                if g in watchlist:
                    acc.removeFromWatchlist(watchlist[g])
                    removed += 1
                    logging.info("  • %s retiré pour %s", watchlist[g].title, user["username"])
            if removed == 0:
                logging.info("  • Aucun changement pour %s", user["username"])
        except Exception as e:
            logging.error("Erreur %s : %s", user["username"], e)

def sync_collections_once():
    wanted_collections = [c.strip() for c in os.getenv("COLLECTIONS", "").split(",") if c.strip()]
    if not wanted_collections:
        logging.warning("Aucune collection définie.")
        return

    logging.info("Collections à surveiller : %s", ", ".join(wanted_collections))

    token  = get_admin_token()
    server = PlexServer(os.getenv("PLEX_URL", "http://localhost:32400"), token=token)
    logging.info("Connecté au serveur Plex local.")

    current = set()
    for name in wanted_collections:
        for lib in server.library.sections():
            if lib.type not in {"movie", "show"}:
                continue
            try:
                coll = next(c for c in lib.collections() if c.title == name)
                nb_items = len(coll.items())
                logging.info("Collection '%s' trouvée dans %s (%d élément(s))", name, lib.title, nb_items)
                current.update(item.guid for item in coll.items())
                break
            except StopIteration:
                logging.warning("Collection '%s' absente de la bibliothèque %s", name, lib.title)

    previous = set(json.load(open(STATE_FILE))) if os.path.exists(STATE_FILE) else set()
    new_guids = current - previous

    logging.info("GUID présents dans les collections : %d", len(current))
    logging.info("GUID déjà connus : %d", len(previous))
    logging.info("Nouveaux GUID à retirer : %d", len(new_guids))

    if new_guids:
        remove_batch(new_guids)
    else:
        logging.info("Rien à retirer, watchlist déjà synchronisée.")

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(list(current), f)
    logging.info("État sauvegardé dans %s", STATE_FILE)

if __name__ == "__main__":
    logging.info("==== Démarrage de plex-watchlist-cleaner ====")
    sync_collections_once()
    logging.info("==== Fin ====")
