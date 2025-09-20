#!/bin/bash
set -x   # ← active le mode debug (chaque commande est affichée avant exécution)

echo "[DEBUG] Début de entrypoint.sh"
echo "[DEBUG] UID=$(id -u) GID=$(id -g)"
echo "[DEBUG] PATH=$PATH"

# Vérifie quels binaires existent
which crontab || echo "[DEBUG] crontab introuvable"
which crond   || echo "[DEBUG] crond   introuvable"
which cron    || echo "[DEBUG] cron    introuvable"
which python3 || echo "[DEBUG] python3 introuvable"
which /usr/local/bin/python || echo "[DEBUG] /usr/local/bin/python introuvable"

# Affiche toutes les vars d’env
env | grep -v no_proxy | tee /tmp/env_dump
printenv >> /etc/environment

CRON_SCHEDULE=${CRON_SCHEDULE:-0 */1 * * *}
echo "[DEBUG] CRON_SCHEDULE=$CRON_SCHEDULE"

# Création du fichier cron temporaire
CRON_FILE=/tmp/crontab
echo "[DEBUG] Écriture cron dans $CRON_FILE"
echo "$CRON_SCHEDULE . /etc/environment; /usr/local/bin/python /app/app.py >> /proc/1/fd/1 2>&1" > "$CRON_FILE"
cat "$CRON_FILE"

# Installation dans crontab
crontab "$CRON_FILE" || echo "[DEBUG] crontab a échoué avec code $?"
crontab -l || echo "[DEBUG] crontab -l a échoué"

echo "[DEBUG] Lancement de l’app Flask principale"
python /app/app.py &

# Puis le cron en avant-plan
if command -v cron >/dev/null 2>&1; then
    echo "[DEBUG] Lancement de cron -f"
    exec cron -f
elif command -v crond >/dev/null 2>&1; then
    echo "[DEBUG] Lancement de crond -f"
    exec crond -f
else
    echo "[DEBUG] Ni cron ni crond trouvés — plantage inévitable"
    exit 127
fi
