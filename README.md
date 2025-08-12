# plex-watchlist-cleaner
Remove media from Plex watchlist when a media is added to certain collections. Works for multiple users.

This little script lets you monitor one or multiple collections in plex, when media are added to these collections it will be automatically removed from the watchlist of all the users you provided.

It was developed in addition to the use of maintainerr in mind. 
For example : if you want to delete media with rules in maintainerr, maintainerr will put them in "Leaving soon", but it cannot remove these media from the watchlist so you need to use list exclusions if you don't want them to be downloaded again. This script will automatically remove the media in "Leaving soon" from the watchlist of all users so you don't need to use list exclusions for them not to be downloaded again.

Checks for new media added to collections automatically.

### Requirements : 
-Unfortunately the only way I found for it to be sustainable is to simulate a login to the Plex API. So you will need to use your username and password but also the usernames and passwords of all the users you want to monitor on their watchlist.

-Plex Media Server

### Exemple of Docker Compose yml :
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
      PLEX_EXTRA_USERS: "usernameFriend1:passFriend1,usernameFriend2:passFriend2"
      CRON_SCHEDULE: "0 */1 * * *"   # every hour
    volumes:
      - ./data:/data
```

I also made a version with webhooks but it's not finished and not maintained, the part for watchlist media deletion is working and it can receive webhooks, but I didn't test it with an agent that automatically sends webhooks. Feel free to update it for your needs. Media is searched by its GUID.

### Notes :
If you add new users after your initial configuration, you will need to delete the data folder in your configured path, otherwise media already present in your collections that need to be deleted will be ignored for the new user.
