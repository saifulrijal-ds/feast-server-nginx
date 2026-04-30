#!/usr/bin/env bash
# Registry runs plain — nginx handles TLS on port 443
set -e

echo "[registry] Starting in plain mode..."
exec feast -c /app/feature_repo serve_registry \
  --port 6570
