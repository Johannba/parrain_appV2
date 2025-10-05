#!/usr/bin/env bash
set -euo pipefail
docker compose exec -T web ./manage.py collectstatic --noinput
