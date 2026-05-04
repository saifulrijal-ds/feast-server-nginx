# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Feast 0.62.0 Proof of Concept** demonstrating a production-ready deployment on AWS EC2 with Docker containers and nginx as a TLS-terminating reverse proxy. The setup exposes only ports 80/443 to the internet; all Feast services (Registry, Offline, Online, UI) run internally in Docker and are inaccessible directly.

The domain is **Multifinance Company Credit Risk modeling** with two feature views: `customer_credit_stats` (7 features) and `customer_behavior_stats` (6 features), materialized from synthetic Parquet data into Redis.

Authentication uses **Feast OIDC AuthZ Manager** backed by **Keycloak 26.2**. Two users are pre-configured via realm auto-import: `alice` (admin — full access) and `bob` (collection_officer — `customer_behavior_stats` read-only).

---

## Development Setup (Python Environment with uv)

This project uses **uv** for fast, reliable Python dependency management. Install uv first: https://docs.astral.sh/uv/getting-started/installation/

**Initialize and sync environment:**
```bash
uv sync                    # Install all dependencies from pyproject.toml
uv sync --no-dev          # Production only (no test/lint tools)
```

**Add new dependencies:**
```bash
uv add package-name        # Add to production dependencies
uv add --dev pytest        # Add to dev dependencies (testing, linting, etc.)
```

**Run code with project environment:**
```bash
uv run python script.py    # Run script in project environment
uv run pytest              # Run tests
uv run black .             # Format code
uv run ruff check .        # Lint code
```

**Update dependency versions:**
```bash
uv lock --upgrade          # Update lock file to latest compatible versions
```

---

## Architecture

### Network & Container Layout

```
Internet (0.0.0.0/0)
    ↓ TLS
nginx (ports 80/443)
    ├─ /feast.registry.* → feast-registry:6570 (gRPC)
    ├─ /feast.serving.* → feast-online:6566 (gRPC)
    ├─ /arrow.flight.protocol.* → feast-offline:8815 (Arrow Flight)
    ├─ /get-online-features, /push, /health → feast-online:6566 (REST)
    ├─ /realms/* → keycloak:8080 (OIDC token acquisition)
    └─ / → feast-ui:8888 (HTTP)

Internal Docker network (no exposure):
    feast-registry, feast-online, feast-offline, feast-ui (all on custom bridge)
    keycloak:8080, postgres:5432, redis:6379
```

**Key design principle**: nginx handles ALL TLS; Feast services run plain (FEAST_TLS=false).

### Container Startup Order

1. **postgres** + **redis** (healthcheck required to proceed)
2. **keycloak** (starts in parallel with feast-init, ~60 s health check on `feast-realm` OIDC discovery)
3. **feast-init** (depends on postgres + redis; runs once, exits with code 0 or blocks all others)
4. **feast-registry**, **feast-offline**, **feast-online**, **feast-ui** (depend on BOTH feast-init success AND keycloak healthy)
5. **nginx** (depends on all Feast services)

### Data Pipeline

- **generate_data.py**: Creates synthetic Parquet files in `feature_repo/data/`
- **feature apply**: Registers entity + feature views to PostgreSQL registry
- **feature materialize**: Loads Parquet → Redis online store (ISO8601 timestamps required)
- **Client requests**: Hit nginx → routed by path to appropriate service → PostgreSQL registry + Redis/offline store

---

## Common Commands

### Server Setup (EC2 Instance)

**Generate TLS certificates** (must be done before first start):
```bash
bash scripts/gen_certs.sh your.public.hostname.com
```
Creates `certs/{server.key, server.crt, ca.crt}`. Copy `ca.crt` to clients.

**Start the full stack**:
```bash
FEAST_HOSTNAME=your.public.hostname.com docker compose up --build
```
First run takes ~2 minutes (synthetic data generation + materialize). Subsequent starts are fast (data persists in Docker volumes).

**Check status**:
```bash
docker compose logs feast-init      # shows init progress
docker logs feast-nginx --tail 20   # shows routed requests
```

**Restart (no rebuild)**:
```bash
docker compose down
FEAST_HOSTNAME=your.public.hostname.com docker compose up -d
```

**Rebuild after code changes**:
```bash
FEAST_HOSTNAME=your.public.hostname.com docker compose up --build
```

### Client Setup (Data Scientist Machine)

**Install dependencies with uv:**
```bash
uv sync                    # Installs feast[redis,postgres] + all project dependencies
```

**Copy CA certificate** from server:
```bash
mkdir -p ~/.feast
scp ubuntu@your.hostname.com:/home/ubuntu/feast-poc-v3/certs/ca.crt ~/.feast/ca.crt
```

**Create `feature_store.yaml`** in your working directory:
```yaml
project: credit_features
entity_key_serialization_version: 3

registry:
  registry_type: remote
  path: your.hostname.com:443
  cert: /home/ubuntu/.feast/ca.crt

offline_store:
  type: remote
  host: your.hostname.com
  port: 443
  scheme: https
  cert: /home/ubuntu/.feast/ca.crt

online_store:
  type: remote
  path: https://your.hostname.com:443
  cert: /home/ubuntu/.feast/ca.crt
```

**Run end-to-end test**:
```bash
uv run python client/test_client.py
```

Expects output showing [1] DISCOVER, [2] TRAINING, [3] SERVING, [4] CONSISTENCY CHECK with latencies.

---

## Key Files & Responsibilities

| File | Purpose |
|------|---------|
| **docker-compose.yml** | Container orchestration, health checks, volumes, dependencies |
| **Dockerfile.feast** | Python 3.11, Feast 0.62.0 + extras, non-root user (feastuser) |
| **feature_repo/feature_definitions.py** | Entity + 2 FeatureViews + 2 Permission objects (RBAC) |
| **feature_repo/generate_data.py** | Synthetic data generator (5000 customers, 2 feature tables) |
| **feature_repo/init.sh** | Orchestrates: generate → apply → materialize |
| **feature_repo/start_*.sh** | Launches registry, offline, online servers (gRPC listening) |
| **nginx/nginx.conf** | Routing by path, TLS config, gRPC proxying, Keycloak proxy |
| **keycloak/realm-export.json** | Auto-imported realm: feast-app client, roles, alice/bob users |
| **scripts/gen_certs.sh** | Self-signed cert + key generation (openssl) |
| **scripts/diagnose.sh** | DNS/connectivity troubleshooter for ngrok/proxies |
| **client/test_client.py** | 4-step client test (no auth — will 401 after auth is enabled) |
| **client/test_rbac.py** | RBAC access test: alice (admin) vs bob (collection_officer) |
| **client/feature_store_alice.yaml** | Client template for alice (admin role) with OIDC auth |
| **client/feature_store_bob.yaml** | Client template for bob (collection_officer role) with OIDC auth |
| **client/feature_store_nginx.yaml** | Template reference — no auth, for unauthenticated local testing |

---

## Feature Definitions

### `customer_credit_stats`
- **Entity**: customer_id
- **TTL**: 90 days
- **Tags**: `team: credit_risk`, `model: risk_prediction`
- **Features**: missed_payments_count, days_past_due, outstanding_balance, credit_utilization_ratio, debt_service_ratio, loan_to_value_ratio, npf_flag

### `customer_behavior_stats`
- **Entity**: customer_id
- **TTL**: 90 days
- **Tags**: `team: credit_risk`, `model: collection_strategy`
- **Features**: avg_monthly_payment, payment_consistency_score, tenor_remaining_months, contract_age_months, early_payment_ratio, payment_trend_3m

Both source from `feature_repo/data/*.parquet` with `event_timestamp` field. Materialized to Redis online store for low-latency serving.

### RBAC Permissions

| Permission name | Role | Covers | Actions |
|---|---|---|---|
| `admin-full-access` | `admin` | all FeatureViews | CREATE, DESCRIBE, UPDATE, DELETE, READ_ONLINE, READ_OFFLINE, WRITE_ONLINE, WRITE_OFFLINE |
| `co-behavior-read` | `collection_officer` | `customer_behavior_stats` only | DESCRIBE, READ_ONLINE, READ_OFFLINE |

### Keycloak Users (auto-imported via `realm-export.json`)

| Username | Password | Keycloak Client Role | Access |
|---|---|---|---|
| `alice` | `password123` | `admin` | Full access to both feature views |
| `bob` | `password123` | `collection_officer` | Read-only on `customer_behavior_stats`; blocked from `customer_credit_stats` |

Roles are **client roles** under the `feast-app` client, NOT realm roles. Feast reads them from `resource_access.feast-app.roles` in the JWT claim.

---

## Important Notes & Gotchas

### Environment Variables

- **FEAST_HOSTNAME**: Required by docker-compose.yml. Set before every `docker compose up`.
- **FEAST_TLS**: Not set (defaults false). Services run plain; nginx handles TLS.
- **FEAST_USAGE**: Set to "False" to disable telemetry.

### Auth-Specific Notes

- **`feast apply` bypasses auth** — it writes directly to PostgreSQL via `registry_type: sql`. The `auth:` block in `feature_store.yaml` is only enforced by the serving servers on incoming gRPC/REST requests.
- **`Permission` import path** in Feast 0.62.0: use `from feast.permissions.permission import Permission`. `from feast import Permission` raises `ImportError`.
- **Server vs client `auth_discovery_url`**: the server uses `http://keycloak:8080/realms/feast-realm/...` (Docker-internal, fetches JWKS directly). Client uses `https://FEAST_HOSTNAME/realms/feast-realm/...` (through nginx). Both point to the same Keycloak; Feast does not validate the `iss` claim so the URL mismatch is safe.
- **`verify_ssl: false`** in client auth config disables TLS verification only for OIDC HTTP calls (the `requests` library). Feast's gRPC connections still use `cert:`. Remove for production (install `ca.crt` into system trust store instead).
- **Keycloak startup** takes ~60 seconds. The feast servers wait for `service_healthy` (realm-specific OIDC endpoint check). Total first-run time is ~3 minutes.
- **`test_client.py` returns 401** once auth is enabled — use `test_rbac.py` instead, which provides OIDC credentials per-request.

### SSL Certificates

- Generated once via `gen_certs.sh`. Contains: `server.key` (private, server-only), `server.crt` (public, nginx), `ca.crt` (distribute to clients).
- Clients must have `ca.crt` in their `feature_store.yaml cert:` path or every gRPC/HTTPS call fails with `SSLCertVerificationError`.
- Self-signed; no external CA involved.

### Registry & Timestamps

- Registry stored in **PostgreSQL** (persists via Docker volume).
- Materialize command requires ISO8601 timestamps: `feast materialize "2020-01-01T00:00:00" "$(date -u +%Y-%m-%dT%H:%M:%S)"`
- Feast 0.62.0 accepts `http` or `https` for offline_store.scheme (not `grpc+tls`).

### Docker Compose Dependencies

Service startup is strictly ordered by `depends_on`. If `feast-init` fails, all three servers are blocked indefinitely. Check logs:
```bash
docker compose logs feast-init
```

### nginx Routing

- Paths like `/feast.registry.*` match prefix (gRPC calls include method names). Use `location /feast.registry { ... }` not `location = /feast.registry`.
- HTTP → HTTPS redirect is automatic (`return 301 https://$host$request_uri`).
- If `/get-online-features` returns 405 Method Not Allowed, restart nginx: `docker compose restart feast-nginx`.

### Port Exposure

- Only 80 and 443 open to Internet (via EC2 Security Group).
- Do NOT open 6566, 6570, 8815, 8888 — they are internal only.
- Verify: `ss -tlnp | grep -E '6566|6570|8815|8888'` should return no output on the host.

---

## Development Workflow

### Modifying Feature Definitions

1. Edit `feature_repo/feature_definitions.py`
2. Restart the stack with rebuild:
   ```bash
   FEAST_HOSTNAME=your.hostname.com docker compose up --build
   ```
3. `feast-init` will apply new definitions to the registry.
4. Test on client: `python client/test_client.py`

### Modifying Data Generation

1. Edit `feature_repo/generate_data.py`
2. Rebuild and restart (same as above).
3. Existing volumes will be wiped on fresh init.

### Modifying nginx Routing

1. Edit `nginx/nginx.conf`
2. Restart nginx only: `docker compose restart feast-nginx`
3. Or full rebuild if structural changes needed.

### Debugging Client Connectivity

Run `scripts/diagnose.sh` on the client machine to check DNS resolution, TLS handshake, and gRPC port reachability.

---

## Testing

**Server-side**: Handled by `feast-init` container (automated via docker-compose).

**Client-side**: Run `python client/test_client.py` from a machine with Feast SDK installed and `feature_store.yaml` configured. Expects:
- [1] Feature discovery via registry gRPC
- [2] Historical features from offline store (Arrow Flight)
- [3] Online serving from online store (REST) with latency < 100ms
- [4] Consistency check (same feature value in both stores)

No unit tests or pytest; POC is integration-test driven.

---

## Troubleshooting Quick Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `SSLCertVerificationError` | Missing or wrong `cert:` path in `feature_store.yaml` | Copy `ca.crt` from server, verify path |
| `Failed to parse port in name` | Registry `path:` is `https://hostname` instead of `hostname:443` | Use `hostname:443` not `https://hostname:443` |
| `Method Not Allowed (405)` | nginx not routing `/get-online-features` | Restart nginx: `docker compose restart feast-nginx` |
| `feast-init` stuck or failing | PostgreSQL/Redis not healthy yet | Wait longer or check `docker compose logs postgres redis` |
| Container keeps restarting | Missing certs or docker-compose syntax error | Check `docker compose logs feast-nginx` and run `docker exec feast-nginx nginx -t` |
| Ports 6566/6570 exposed to host | Security misconfiguration | Verify Security Group rules; only 80/443 should be open |
| `401 Unauthenticated` | Token not acquired or wrong `client_secret` | Verify client YAML `client_secret: feast-secret`; confirm `docker compose logs feast-keycloak` shows realm imported |
| `403 Permission Denied` (unexpected) | Role name mismatch (case-sensitive) | Decode JWT at jwt.io; check `resource_access.feast-app.roles` matches exactly |
| Roles missing from JWT | Assigned Realm Role instead of Client Role | Keycloak admin → `feast-app` client → Roles tab; reassign user there |
| Feast servers not starting (waiting for keycloak) | Keycloak healthcheck failing | `docker compose logs feast-keycloak` — realm import takes ~60 s |
| `ImportError: cannot import name 'Permission' from 'feast'` | Wrong import in Feast 0.62.0 | Use `from feast.permissions.permission import Permission` |

---

## Resources

- **README.md**: Full step-by-step server & client setup, feature reference
- **DATA_SUMMARY.md**: Synthetic data schema and example rows
- **docker-compose.yml**: Service definitions, health checks, dependencies
- **nginx/nginx.conf**: Full routing logic, TLS config, gRPC proxy settings
- **Feast Docs**: https://docs.feast.dev (registry, offline/online stores, materialization)
