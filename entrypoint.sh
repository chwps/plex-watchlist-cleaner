#!/bin/bash
# Assure que toutes les variables d’environnement soient visibles par cron
printenv | grep -v "no_proxy" >> /etc/environment

# CRON par défaut toutes les heures
CRON_SCHEDULE=${CRON_SCHEDULE:-0 */1 * * *}

# On construit la ligne cron :
#   – on « source » /etc/environment pour retrouver toutes les vars
#   – on redirige stdout/stderr vers le même flux que PID 1
CRON_CMD="$CRON_SCHEDULE . /etc/environment; /usr/local/bin/python /app/app.py >> /proc/1/fd/1 2>&1"

# Injection de la tâche (création ou remplacement)
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "[ENTRYPOINT] Starting cron in foreground..."
cron -f
