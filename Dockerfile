FROM python:3.11-slim

# Installer cron + busybox (léger)
RUN apt-get update && \
    apt-get install -y cron busybox && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh app.py ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
