#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
#  Feast Remote Connectivity Diagnostics
#  Usage:  ./scripts/diagnose.sh feast.your-company.com
#  Output: tells you exactly what is failing and why
# ═══════════════════════════════════════════════════════
HOST="${1:-localhost}"
RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GRN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YEL}!${NC} $1"; }

echo ""
echo "══════════════════════════════════════════════════"
echo "  Feast Remote Diagnostics → $HOST"
echo "══════════════════════════════════════════════════"

# ── 1. DNS resolution ──────────────────────────────────
echo ""
echo "1. DNS resolution"
if ip=$(python3 -c "import socket; print(socket.gethostbyname('$HOST'))" 2>/dev/null); then
  ok "$HOST  →  $ip"
else
  fail "Cannot resolve '$HOST'"
  echo "  Fix A: echo '<SERVER_IP> $HOST' | sudo tee -a /etc/hosts"
  echo "  Fix B: use the raw IP in feature_store.yaml instead of hostname"
fi

# ── 2. TCP port connectivity ───────────────────────────
echo ""
echo "2. TCP port connectivity"
for PORT in 6566 6570 8815 8888; do
  case $PORT in
    6566) LABEL="Online server  (REST HTTP)";;
    6570) LABEL="Registry server (gRPC)";;
    8815) LABEL="Offline server  (Arrow Flight)";;
    8888) LABEL="Web UI";;
  esac
  if python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(3)
sys.exit(0 if s.connect_ex(('$HOST', $PORT)) == 0 else 1)
" 2>/dev/null; then
    ok "$PORT  $LABEL  — open"
  else
    fail "$PORT  $LABEL  — refused / blocked"
    echo "     Fix: open port $PORT in server firewall / cloud security group"
  fi
done

# ── 3. HTTP health — Online server ────────────────────
echo ""
echo "3. Online server HTTP health (:6566)"
CODE=$(python3 -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://$HOST:6566/health', timeout=5)
    print(r.status)
except Exception as e:
    print(f'ERR:{e}')
" 2>/dev/null)
if [ "$CODE" = "200" ]; then
  ok "/health → 200 OK  (plaintext HTTP works)"
else
  warn "/health → $CODE"
  warn "If behind HTTPS/nginx: update feature_store.yaml → path: https://$HOST:6566"
fi

# ── 4. Arrow Flight scheme test ────────────────────────
echo ""
echo "4. Arrow Flight scheme test (:8815)"
python3 - <<'PYEOF' 2>/dev/null || echo "  (pyarrow not installed — run: pip install pyarrow)"
import sys
HOST = sys.argv[1] if len(sys.argv) > 1 else "HOST_PLACEHOLDER"
import pyarrow.flight as fl

def try_scheme(scheme):
    try:
        client = fl.connect(f"{scheme}://{HOST}:8815")
        client.wait_for_available(timeout=4)
        return True
    except:
        return False

if try_scheme("grpc"):
    print("  \033[0;32m✓\033[0m  scheme: grpc  (insecure) works")
    print("  → set scheme: grpc  in offline_store config")
elif try_scheme("grpc+tls"):
    print("  \033[0;32m✓\033[0m  scheme: grpc+tls  (TLS) works")
    print("  → set scheme: grpc+tls  in offline_store config + provide cert:")
else:
    print("  \033[0;31m✗\033[0m  Both grpc:// and grpc+tls:// failed")
    print("  → Check port 8815 is open and feast serve_offline is running")
PYEOF
# Pass host as argument - replace placeholder in heredoc workaround
python3 -c "
import sys, pyarrow.flight as fl
HOST='$HOST'
for scheme in ['grpc', 'grpc+tls']:
    try:
        c = fl.connect(f'{scheme}://{HOST}:8815')
        c.wait_for_available(timeout=4)
        print(f'  \033[0;32m✓\033[0m scheme={scheme} works → use in feature_store.yaml')
        break
    except Exception as e:
        print(f'  \033[0;31m✗\033[0m scheme={scheme} failed: {e}')
" 2>/dev/null || true

# ── 5. Summary ─────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "  Correct client feature_store.yaml for: $HOST"
echo "══════════════════════════════════════════════════"
cat << YAML

project: bfi_credit_features
entity_key_serialization_version: 2

registry:
  registry_type: remote
  path: http://$HOST:6570       # scheme (http://) REQUIRED for remote host

offline_store:
  type: remote
  host: $HOST
  port: 8815
  scheme: grpc                  # REQUIRED for non-localhost (insecure)
  # scheme: grpc+tls            # use if TLS is enabled on the server

online_store:
  type: remote
  path: http://$HOST:6566      # http:// or https:// must be explicit

YAML
