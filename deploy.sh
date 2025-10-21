# #!/usr/bin/env bash
# set -euo pipefail

# echo "[deploy] Pull code & build image"
# git fetch --all
# git checkout main
# git pull --ff-only

# echo "[deploy] Create .env if missing"
# if [ ! -f .env ]; then
#   cp .env.example .env
#   echo ">>> .env created from .env.example (update secrets!)"
# fi

# echo "[deploy] Start/Update stack"
# docker compose pull || true
# docker compose build --no-cache
# docker compose up -d

# echo "[deploy] Run migrations & collectstatic"
# docker compose exec -T web ./manage.py migrate --noinput
# docker compose exec -T web ./manage.py collectstatic --noinput

# echo "[deploy] Smoke tests"
# ./smoke.sh

# echo "[deploy] Done."
#!/usr/bin/env bash
set -euo pipefail

cd /root/parrain_appV2

echo "==> Git: update main"
git fetch origin
git switch main
git pull --ff-only origin main

echo "==> Build & restart web"
docker compose build web
docker compose up -d web

echo "==> Django: migrate + collectstatic"
docker compose exec -T web ./manage.py migrate --noinput
docker compose exec -T web ./manage.py collectstatic --noinput

echo "==> Smoke tests"
docker compose exec -T web sh -lc "sed -n '1,8p' /app/templates/public/home.html"
docker compose exec -T web sh -lc "curl -sSI -H 'Host: chuchote.com' http://127.0.0.1:8000/healthz/ | head -n 8"

echo "✅ Deploy OK"
