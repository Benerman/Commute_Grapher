FROM python:3.11-slim

# Install curl for fetching supercronic
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install supercronic (tiny cron runner for containers)
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64
RUN curl -fsSL "$SUPERCRONIC_URL" -o /usr/local/bin/supercronic \
 && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Files are bind-mounted by compose:
# - /app/route_fetch_travel_time.py
# - /etc/cron.d/commute (from fetcher/cron/commute)
