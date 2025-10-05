#!/usr/bin/env bash
set -euo pipefail

DB_DUMP="${1:-}"
MEDIA_TGZ="${2:-}"

if [ -z "${DB_DUMP}" ]; then
  echo "Usage: $0 backups/db-YYYYMMDD-HHMMSS.sql.gz [backups/media-YYYYMMDD-HHMMSS.tgz]"
  exit 1
fi

echo "[restore] Stopping web to avoid writes"
docker compose stop web || true

echo "[restore] Restoring DB from ${DB_DUMP}"
gunzip -c "${DB_DUMP}" | docker compose exec -T postgres psql -U "${POSTGRES_USER:-parrainapp}" "${POSTGRES_DB:-parrainapp}"

if [ -n "${MEDIA_TGZ}" ]; then
  echo "[restore] Restoring media from ${MEDIA_TGZ}"
  docker compose run --rm --no-deps -v "$(pwd)/${MEDIA_TGZ}:/in.tgz" web         bash -lc "rm -rf /app/media/* && tar xzf /in.tgz -C / --warning=no-unknown-keyword"
fi

echo "[restore] Restart web"
docker compose up -d web
echo "[restore] Done."
