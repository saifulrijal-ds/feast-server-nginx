#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  Feast Client Setup — run this on the DS local machine
#  Usage:
#    Plain:  ./setup_client.sh feast.bfi-dev.internal
#    nginx:  ./setup_client.sh feast.bfi.co.id nginx /path/to/ca.crt
# ═══════════════════════════════════════════════════════
set -e

HOST="${1:?Usage: $0 <server-host> [plain|nginx] [/path/to/ca.crt]}"
MODE="${2:-plain}"
CERT="${3:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "══════════════════════════════════════"
echo "  Feast Client Setup"
echo "  Host : $HOST"
echo "  Mode : $MODE"
echo "══════════════════════════════════════"

# 1. Install SDK
echo ""
echo "→ [1/3] Installing feast SDK..."
pip install --quiet "feast[redis,postgres]==0.62.0" pyarrow pandas

# 2. Generate feature_store.yaml from template
echo ""
echo "→ [2/3] Writing feature_store.yaml..."
export FEAST_SERVER_HOST="$HOST"
export FEAST_CERT_PATH="${CERT:-/path/to/ca.crt}"

if [ "$MODE" = "nginx" ]; then
  envsubst < "$SCRIPT_DIR/feature_store_nginx.yaml" > "$SCRIPT_DIR/feature_store.yaml"
  echo "  Written: client/feature_store.yaml (nginx mode — single port 443)"
  if [ -z "$CERT" ]; then
    echo "  ⚠ Copy ca.crt from server first:"
    echo "     scp ubuntu@${HOST}:/path/to/feast-poc-v3/certs/ca.crt ~/.feast/ca.crt"
    echo "     Then re-run: $0 $HOST nginx ~/.feast/ca.crt"
  fi
else
  envsubst < "$SCRIPT_DIR/feature_store_plain.yaml" > "$SCRIPT_DIR/feature_store.yaml"
  echo "  Written: client/feature_store.yaml (plain mode)"
fi

# 3. Run diagnostics
echo ""
echo "→ [3/3] Running connectivity check..."
bash "$SCRIPT_DIR/../scripts/diagnose.sh" "$HOST"

echo ""
echo "  Done. Run:  python test_client.py"
