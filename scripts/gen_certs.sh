#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  Generate self-signed TLS certificates for Feast servers
#  with DNS SAN (Subject Alternative Name) so remote gRPC
#  and Arrow Flight clients can connect by hostname/IP.
#
#  Usage:
#    ./scripts/gen_certs.sh feast.mycompany.com
#    ./scripts/gen_certs.sh 10.0.1.25          # raw IP also works
#
#  Outputs to: ./certs/
#    server.key  – private key (keep on server only)
#    server.crt  – public cert  (share with DS clients)
#    ca.crt      – CA bundle (same as server.crt for self-signed)
# ═══════════════════════════════════════════════════════════
set -e

HOSTNAME="${1:?Usage: $0 <hostname-or-ip>}"
CERTS_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERTS_DIR"

echo ""
echo "Generating self-signed TLS cert for: $HOSTNAME"
echo "Output dir: $CERTS_DIR"

# Determine if hostname is an IP address or DNS name
if [[ "$HOSTNAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN_LINE="IP:${HOSTNAME},IP:127.0.0.1"
else
  SAN_LINE="DNS:${HOSTNAME},DNS:localhost,IP:127.0.0.1"
fi

# Generate private key + self-signed cert with SAN
openssl req -x509 -nodes -newkey rsa:4096 \
  -keyout "$CERTS_DIR/server.key" \
  -out    "$CERTS_DIR/server.crt" \
  -days 365 \
  -subj "/CN=${HOSTNAME}/O=BFI Finance/OU=Data Innovation" \
  -addext "subjectAltName=${SAN_LINE}" \
  -addext "basicConstraints=CA:TRUE" \
  2>/dev/null

# Copy as CA cert (self-signed = CA is the cert itself)
cp "$CERTS_DIR/server.crt" "$CERTS_DIR/ca.crt"

echo ""
echo "  ✓  certs/server.key   (server private key — DO NOT share)"
echo "  ✓  certs/server.crt   (server public cert)"
echo "  ✓  certs/ca.crt       (CA cert — copy to DS client machines)"
echo ""
echo "  SAN entries: $SAN_LINE"
echo ""
echo "Next steps:"
echo "  1. Keep certs/server.key + certs/server.crt on the server"
echo "  2. Copy certs/ca.crt to each DS client machine"
echo "  3. docker compose up (TLS config picks up certs/ automatically)"
