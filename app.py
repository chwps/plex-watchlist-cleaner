#!/usr/bin/env python3
import os
import json
import logging
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

STATE_FILE = "/data/plex_watchlist_state.json"

def remove_from_watchlist_for_all(guid: str):
    creds = [{"username": os.getenv("PLEX_USERNAME"), "password": os.getenv("PLEX_PASSWORD")}]
    extra = os.getenv("PLEX_EXTRA_USERS", "")
    for pair in extra.split(","):
        if ":" in pair:
            u, p = pair.split(":", 1)
            creds.append({"username": u.strip(), "password": p.strip()})

    for c in creds:
        try:
            acc = MyPlexAccount(c["username"], c["password"])
            for item in acc.watchlist():
                if item.guid == guid:
                    acc.removeFromWatchlist(item)
                    logging.info("Removed %s for %s", item.title, c["username"])
                    break
        except Exception as e:
            logging.error("Failed %s: %s", c["username"], e)


def sync_collections_once():
    collections = os.getenv("COLLECTIONS", "").split(",")
    if not collections:
        logging.warning("No collections defined")
        return

    server = PlexServer(
        os.getenv("PLEX_URL", "http://localhost:32400"),
        token=None
    )
    server = MyPlexAccount(
        os.getenv("PLEX_USERNAME"),
        os.getenv("PLEX_PASSWORD")
    ).resource().connect()

    current = set()
    for name in map(str.strip, collections):
        for lib in server.library.sections():
            if lib.type in {"movie", "show"}:
                try:
                    coll = lib.collection(title=name)[0]
                    current.update(item.guid for item in coll.items())
                except IndexError:
                    continue

    previous = set(json.load(open(STATE_FILE))) if os.path.exists(STATE_FILE) else set()
    new_guids = current - previous

    for guid in new_guids:
        remove_from_watchlist_for_all(guid)

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(list(current), f)


if __name__ == "__main__":
    sync_collections_once()
