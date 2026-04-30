#!/usr/bin/env bash
# Online server runs plain HTTP — nginx handles TLS on port 443
set -e

echo "[online] Starting in plain HTTP mode..."
exec feast -c /app/feature_repo serve \
  --host 0.0.0.0 --port 6566
