#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR_HOST="./backups"
mkdir -p "${BACKUP_DIR_HOST}"

echo "[backup] Postgres dump"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-parrainapp}" "${POSTGRES_DB:-parrainapp}"       | gzip > "${BACKUP_DIR_HOST}/db-${STAMP}.sql.gz"

echo "[backup] Media archive"
docker compose run --rm --no-deps -v "$(pwd)/${BACKUP_DIR_HOST}:/out" backup       bash -lc "cd / && tar czf /out/media-${STAMP}.tgz media || true"

echo "[backup] Rotate (keep last 30)"
ls -1t ${BACKUP_DIR_HOST}/db-*.sql.gz | sed -e '1,30d' | xargs -r rm -f
ls -1t ${BACKUP_DIR_HOST}/media-*.tgz   | sed -e '1,30d' | xargs -r rm -f

echo "[backup] Done: ${BACKUP_DIR_HOST}"
