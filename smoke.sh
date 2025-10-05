#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-chuchote.com}"

echo "[smoke] HTTP 200 on /healthz or /"
curl -I --max-time 10 "https://${DOMAIN}/healthz" || true
curl -I --max-time 10 "https://${DOMAIN}/" || (echo "Homepage not reachable" && exit 1)

echo "[smoke] Email test placeholder (adjust to your project)"
# docker compose exec -T web ./manage.py send_test_email ops@chuchote.com || true

echo "[smoke] SMS test placeholder (set SMSMODE_DRY_RUN=true first)"
# docker compose exec -T web ./manage.py send_test_sms +33XXXXXXXXX "Hello from prod (dry)" || true

echo "[smoke] OK"
