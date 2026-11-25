FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# PROVIDER=browser drives a real Chromium in this container, so the request
# carries a browser's own session instead of a copied cookie. It runs headed
# under Xvfb on purpose: headless Chromium announces itself in the UA and in a
# few fingerprints, and looking like a browser is the entire point.
# x11vnc is only used by `python -m app.browser_login` (one-time, port 5900).
ENV CHROMIUM_PATH=/usr/bin/chromium \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb xauth x11vnc xclip fonts-dejavu-core ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY docker-entrypoint.sh ./

RUN useradd --uid 1000 --create-home app \
 && mkdir -p /data /data/backups \
 && chown -R 1000:1000 /data

USER 1000
EXPOSE 8080

# Reports unhealthy when the process cannot serve, not when Instagram is down:
# sync failure must degrade the app, never restart it.
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3)"

CMD ["./docker-entrypoint.sh"]
