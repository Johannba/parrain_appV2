#!/usr/bin/env bash
set -euo pipefail

echo "[deploy] Pull code & build image"
git fetch --all
git checkout main
git pull --ff-only

echo "[deploy] Create .env if missing"
if [ ! -f .env ]; then
  cp .env.example .env
  echo ">>> .env created from .env.example (update secrets!)"
fi

echo "[deploy] Start/Update stack"
docker compose pull || true
docker compose build --no-cache
docker compose up -d

echo "[deploy] Run migrations & collectstatic"
docker compose exec -T web ./manage.py migrate --noinput
docker compose exec -T web ./manage.py collectstatic --noinput

echo "[deploy] Smoke tests"
./smoke.sh

echo "[deploy] Done."
