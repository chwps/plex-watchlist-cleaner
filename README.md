# plex-watchlist-cleaner
Remove media from Plex watchlist when a media is added to certains collections. Works for multiple users.

This little script lets you monitor one or multiple collections in plex, when media are added to theses collections it will be automatically removed from the watchlist of all the users you provided.

It was developped in addition to the use of maintainerr. 
For example if you want to delete media with rules in maintainerr, maintainerr will put them in "Leaving soon", but it cannot remove theses medias from the watchlist so you need to use list exclusions if you don't want them to be downloaded again. This script will automatically remove the medias in "Leaving soon" from the watchlist of all user so you don't need to use list exclusions for them not to be downloaded again.

###Requirements : 
-Unfortunatly the only way I found for it to be sustainable is to simulate a login to plex api. So you will need to use your username and password but also the usernames and passwords of all the users you want to monitor their watchlist.

-Plex Media Server

Exemple of docker compose yml :
```yaml
version: "3.9"
services:
  plex-watchlist-cleaner:
    image: ghcr.io/chwps/plex-watchlist-cleaner:latest
    container_name: plex-watchlist-cleaner
    restart: unless-stopped
    environment:
      PLEX_URL: "http://localhost:32400"
      PLEX_USERNAME: "admin"
      PLEX_PASSWORD: "adminpass"
      COLLECTIONS: "Collection1,Collection2,Collection3"
      PLEX_EXTRA_USERS: "ami1:pass1,ami2:pass2"
      CRON_SCHEDULE: "0 */1 * * *"   # every hour
    volumes:
      - ./data:/data
```
