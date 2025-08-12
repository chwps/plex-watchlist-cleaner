#!/bin/sh

# CRON_SCHEDULE env variable (default every hour)
CRON_SCHEDULE=${CRON_SCHEDULE:-0 */1 * * *}

# Write cron line and launch crond
echo "$CRON_SCHEDULE /usr/local/bin/python /app/app.py >> /var/log/sync.log 2>&1" | crontab -
exec crond -f
