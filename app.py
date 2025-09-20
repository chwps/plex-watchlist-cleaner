#!/usr/bin/env python3
import json, os, logging
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

logging.basicConfig(level=logging.INFO)

TOKENS_FILE = "/data/user_tokens.json"
STATE_FILE  = "/data/plex_watchlist_state.json"

def load_tokens():
    return json.load(open(TOKENS_FILE)) if os.path.exists(TOKENS_FILE) else {}

def list_all_users():
    """Renvoie [{username, token}] sans jamais demander de mot de passe."""
    tokens = load_tokens()
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
