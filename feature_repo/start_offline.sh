#!/usr/bin/env bash
# Offline (Arrow Flight) runs plain — nginx handles TLS on port 443
set -e

echo "[offline] Starting Arrow Flight in plain mode..."
exec feast -c /app/feature_repo serve_offline \
  --host 0.0.0.0 --port 8815
