#!/bin/sh
# Rebuilds the container when origin/main has moved; run by seo-api-deploy.timer.
set -eu
cd /opt/seo-api
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
git merge -q --ff-only origin/main
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
echo "deployed $(git rev-parse --short HEAD)"
