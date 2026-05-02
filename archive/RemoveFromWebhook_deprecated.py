from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import logging
from plexapi.myplex import MyPlexAccount
import json
import sys
from plexapi.server import PlexServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
load_dotenv()

app = Flask(__name__)

def remove_from_watchlist(plex_id: str):
    username = os.getenv('PLEX_USERNAME')
    password = os.getenv('PLEX_PASSWORD')

    try:
        account = MyPlexAccount(username, password)
        watchlist = account.watchlist()

        logging.info("Watchlist actuelle :")
        for item in watchlist:
            logging.info("%s - key=%s - guid=%s", item.title, item.key, item.guid)

        # Normaliser l'identifiant
        if plex_id.startswith("/library/metadata/"):
            wanted_key = plex_id
        elif plex_id.isdigit():
            wanted_key = f"/library/metadata/{plex_id}"
        else:
            wanted_key = plex_id  # Fallback si jamais c'est un guid complet

        # Chercher dans la watchlist
        item_to_remove = None
        for item in watchlist:
            if item.key == wanted_key or item.guid == wanted_key:
                item_to_remove = item
                break

        if item_to_remove:
            title = item_to_remove.title
            logging.info(f"Suppression de '{title}' de la watchlist")
            account.removeFromWatchlist(item_to_remove)
            logging.info("Média retiré de la watchlist.")
            return True, title
        else:
            logging.info(f"Aucun média avec ratingKey={plex_id} trouvé dans la watchlist.")
            return False, None

    except Exception as e:
        logging.error(f"Erreur lors de la suppression : {e}")
        return False


def remove_from_watchlist_for_all(plex_id: str):
    """
    Retire le média identifié par plex_id de la watchlist
    pour chaque utilisateur listé dans USER_CREDENTIALS.
    USER_CREDENTIALS est une liste de dicts : {"username": "...", "password": "..."}
    """

    # 1) Charger la liste des comptes (admin + amis)
    credentials = [
        {"username": os.getenv("PLEX_USERNAME"), "password": os.getenv("PLEX_PASSWORD")}  # admin
    ]

    # Ajoute ici les amis :
    extra_accounts = os.getenv("PLEX_EXTRA_USERS", "")   # format : user1:pass1,user2:pass2
    for pair in extra_accounts.split(","):
        if ":" in pair:
            u, p = pair.split(":", 1)
            credentials.append({"username": u.strip(), "password": p.strip()})

    # 2) Traiter chaque compte
    results = {}
    for cred in credentials:
        try:
            account = MyPlexAccount(cred["username"], cred["password"])
            watchlist = account.watchlist()

            wanted = plex_id.strip()
            if wanted.isdigit():
                wanted = f"/library/metadata/{wanted}"

            for item in watchlist:
                if item.key == wanted or item.guid == wanted:
                    account.removeFromWatchlist(item)
                    results[account.username] = (True, item.title)
                    logging.info("Retiré pour %s : %s", account.username, item.title)
                    break
            else:
                results[account.username] = (False, None)
                logging.info("Non trouvé pour %s", account.username)
        except Exception as e:
            logging.error("Erreur avec %s : %s", cred["username"], e)
            results[cred["username"]] = (False, None)

    return results
    

@app.route('/webhook', methods=['POST'])
def webhook():
    logging.info("Webhook reçu")

    # Plex envoie form-data avec un champ 'payload'
    if request.content_type and 'application/x-www-form-urlencoded' in request.content_type:
        payload_str = request.form.get('payload')
        if payload_str:
            try:
                data = json.loads(payload_str)
            except Exception as e:
                logging.error("Impossible de parser le payload JSON : %s", e)
                return jsonify({"status": "error", "message": "JSON invalide"}), 400
        else:
            logging.error("Pas de champ 'payload' dans le form-data")
            return jsonify({"status": "error", "message": "Champ payload manquant"}), 400
    else:
        # Fallback si Plex envoyait JSON brut
        data = request.get_json(force=True, silent=True) or {}

    logging.info("Payload extraite : %s", data)

    if data.get('notification_type') == 'media_removed':
        plex_id = None
        if 'extra' in data and 'plexId' in data['extra']:
            plex_id = data['extra']['plexId']
        elif 'plexId' in data:
            plex_id = data['plexId']

        if plex_id:
            results = remove_from_watchlist_for_all(plex_id)

            # 2) on compte les succès
            removed = [title for success, title in results.values() if success]

            if removed:
                return jsonify({
                    "status": "success",
                    "message": f"'{', '.join(removed)}' retire(s) de la watchlist"
                }), 200
            else:
                return jsonify({
                    "status": "not_found",
                    "message": "Media non trouve dans aucune watchlist"
                }), 404
        else:
            return jsonify({"status": "error", "message": "Pas d'identifiant Plex fourni"}), 400

    return jsonify({"status": "ignored", "message": "Notification non traitée"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

