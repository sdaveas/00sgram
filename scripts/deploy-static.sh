#!/bin/sh
# Deploy app/static into the running container, no rebuild. Python changes need
# \`docker compose build web\` instead; this script only moves JS/CSS/HTML.
set -e
cd "$(dirname "$0")/.."
docker cp app/static/. 00sgram-web-1:/app/app/static/
echo "copied; probing:"
for f in app.js views.js browse.js str.js style.css; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8091/static/$f")
  echo "  $f $code"
done
curl -s http://127.0.0.1:8091/ | grep -c 'id="app"' | sed 's/^/  #app in index: /'
