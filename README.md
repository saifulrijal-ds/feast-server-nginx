# Feast 0.62.0 — Production Feature Store on AWS EC2

A learning-oriented proof-of-concept showing how to deploy a complete
**Feature Store** for a Multifinance Company credit risk team — with TLS,
authentication, role-based access control, and named feature bundles per model.

---

## What You Will Learn

By running this project end-to-end you will understand:

1. What a feature store does and why it exists
2. How Feast separates **offline** (training) and **online** (serving) stores
3. How **nginx** acts as the single public gateway for three different protocols
4. How **Keycloak OIDC** authenticates users and how Feast enforces **RBAC**
5. What a **FeatureService** is and why it matters for MLOps
6. How two different data scientists (alice and bob) see different data from the same server

---

## Key Concepts

### Feature Store

A feature store is the data layer between raw data and ML models. It solves two problems:

| Problem | Solution |
|---|---|
| **Training-serving skew** — model trained on different values than it serves | Both training and serving read features from the same definitions |
| **Repeated feature engineering** — every team reinvents the same transformations | Define once, reuse across all models |

### Offline vs Online Store

| Store | Purpose | Technology | Latency |
|---|---|---|---|
| **Offline** | Historical features for model training | Parquet files (Arrow Flight) | ~100s ms for bulk |
| **Online** | Latest features for real-time serving | Redis | ~1–10 ms |

`feast materialize` copies the latest snapshot from offline → online. The same feature definitions govern both.

### FeatureService

A `FeatureService` is a named, versioned bundle of features for a specific model.
Instead of passing 13 `"view:feature"` strings, the model calls one named service:

```python
# Without FeatureService — fragile, not versioned
features=["customer_credit_stats:npf_flag", "customer_credit_stats:days_past_due", ...]

# With FeatureService — versioned contract, managed centrally
features=store.get_feature_service("npf_prediction_service")
```

Two services are defined in this project:

| Service | Features | Who Can Access |
|---|---|---|
| `npf_prediction_service` | All 7 credit + 2 behavior features | `admin` only |
| `collection_strategy_service` | All 6 behavior features | `admin` + `collection_officer` |

### RBAC — Two Layers

Authentication (who are you?) and authorization (what can you do?) are handled by two different systems:

```
Keycloak                           Feast Permission objects
────────────────────               ─────────────────────────────────
Issues JWT token                   Check roles from JWT against
with role in:                      RoleBasedPolicy per resource:
resource_access
  .feast-app
    .roles: ["admin"]   ─────────► Permission(types=[FeatureView],
                                              policy=RoleBasedPolicy(["admin"]))
```

The role name string is the only contract between these two systems. If they don't match exactly (case-sensitive), every request returns 403.

---

## Architecture

```
Internet (ports 80, 443 only)
        │
        ▼
  nginx :443 (TLS termination — only public entry point)
        │
        ├── /feast.registry.*          grpc://feast-registry:6570
        ├── /feast.serving.*           grpc://feast-online:6566
        ├── /arrow.flight.protocol.*   grpc://feast-offline:8815
        ├── /get-online-features       http://feast-online:6566   (REST)
        ├── /realms/*                  http://keycloak:8080        (OIDC)
        └── /                         http://feast-ui:8888

Internal Docker network (never exposed to internet):
    feast-registry  feast-offline  feast-online  feast-ui
    keycloak        postgres       redis
```

**Why three different protocols on one port?**
nginx routes by HTTP/2 path prefix. gRPC encodes the service name in the
`:path` header (e.g., `/feast.registry.RegistryServer/GetRegistry`), so nginx
can distinguish gRPC from REST without inspecting request bodies.

### Container Startup Order

```
postgres ──┐
           ├──► feast-init (generate → apply → materialize) ──┐
redis   ───┘                                                   │
                                                               ├──► feast-registry  ──┐
keycloak (~60s to import realm) ───────────────────────────────┘──► feast-offline   ──├──► nginx
                                                                  ► feast-online    ──┘
                                                                  ► feast-ui
```

If `feast-init` fails (e.g., PostgreSQL not ready), the three servers never start.
If Keycloak takes too long to become healthy, the servers wait indefinitely.
Check with `docker compose logs feast-init` if anything seems stuck.

---

## Project File Map

```
feast-poc-v3/
├── docker-compose.yml              Container orchestration + startup order
├── Dockerfile.feast                Python 3.11 + Feast 0.62.0 image
├── nginx/
│   └── nginx.conf                  Protocol routing + TLS config
├── keycloak/
│   └── realm-export.json           Auto-imported realm: roles, users, client
├── feature_repo/
│   ├── feature_store.yaml          Server-side config (PostgreSQL + Redis + OIDC)
│   ├── feature_definitions.py      Entity, FeatureViews, FeatureServices, Permissions
│   ├── generate_data.py            Synthetic Parquet data (2000 customers, 6 snapshots)
│   ├── init.sh                     Bootstrap: generate → feast apply → materialize
│   ├── start_registry.sh           Launches gRPC registry server
│   ├── start_offline.sh            Launches Arrow Flight offline server
│   └── start_online.sh             Launches REST + gRPC online server
├── certs/                          TLS certs (created by gen_certs.sh, git-ignored)
├── scripts/
│   ├── gen_certs.sh                Self-signed TLS cert generator
│   └── diagnose.sh                 Connectivity troubleshooter
├── pyproject.toml                  Python dependencies managed with uv
├── client/
│   ├── feature_store.yaml          Active client config (edit hostname here)
│   ├── feature_store_alice.yaml    Template for alice (admin) — uses envsubst
│   ├── feature_store_bob.yaml      Template for bob (collection_officer) — uses envsubst
│   └── test_client.py              5-step end-to-end test authenticated as alice
│   └── test_rbac.py                RBAC test: alice vs bob, FeatureView + FeatureService
└── README.md                       This file
```

---

## Part 1 — Server Setup

### Step 1 — Open Firewall Ports (EC2 Security Group)

In the AWS Console → EC2 → Security Groups, add inbound rules:

| Type  | Protocol | Port | Source    | Reason |
|-------|----------|------|-----------|--------|
| HTTP  | TCP      | 80   | 0.0.0.0/0 | Redirect to HTTPS |
| HTTPS | TCP      | 443  | 0.0.0.0/0 | All Feast + Keycloak traffic |
| SSH   | TCP      | 22   | your IP   | Management |

> **Do NOT open** 6566, 6570, 8815, or 8888. Those are Feast-internal ports
> that only nginx needs to reach. Exposing them bypasses authentication entirely.

---

### Step 2 — Get the Public DNS Name

Run this on the EC2 instance to retrieve the public hostname:

```bash
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-hostname
```

Example: `ec2-16-78-34-107.ap-southeast-3.compute.amazonaws.com`

Save this value — you will use it in every step below.

---

### Step 3 — Generate TLS Certificates

```bash
bash scripts/gen_certs.sh ec2-16-78-34-107.ap-southeast-3.compute.amazonaws.com
```

This creates three files in `certs/`:

| File | Purpose | Share? |
|---|---|---|
| `server.key` | Private key used by nginx | Server only — never share |
| `server.crt` | Server certificate | Server only |
| `ca.crt` | CA bundle (self-signed = same as crt) | Copy to every client machine |

> **Why a custom CA?** The cert is self-signed — no public CA validates it.
> Clients need `ca.crt` so their gRPC and HTTPS calls can verify the server.
> Without it, every connection fails with `SSLCertVerificationError`.

> **Important:** If you get a new EC2 instance (different public hostname),
> regenerate the cert. The old cert's Subject Alternative Name won't cover
> the new hostname and all client connections will fail TLS verification.

---

### Step 4 — Start the Stack

```bash
FEAST_HOSTNAME=ec2-16-78-34-107.ap-southeast-3.compute.amazonaws.com \
  docker compose up --build
```

What happens on first run:

1. **postgres + redis** start and become healthy
2. **feast-init** runs three steps sequentially:
   - `generate_data.py` → creates synthetic Parquet files (2000 customers, 6 time snapshots)
   - `feast apply` → registers Entity, FeatureViews, FeatureServices, Permissions to PostgreSQL
   - `feast materialize` → copies latest feature values from Parquet into Redis
3. **keycloak** imports `realm-export.json` in parallel (~60s) — creates `feast-realm`, roles, and users
4. Once **both** feast-init succeeds AND keycloak is healthy → feast-registry, feast-offline, feast-online, feast-ui start
5. **nginx** starts last, resolves all upstream hostnames and begins routing

First run takes **~3 minutes**. Subsequent starts are fast (data persists in Docker volumes).

---

### Step 5 — Verify the Server

```bash
# All containers should be Up
docker compose ps

# feast-init ran successfully
docker compose logs feast-init | tail -10

# nginx is routing (check for routed requests)
docker logs feast-nginx --tail 20

# Feast ports are NOT visible on the host (should return empty)
ss -tlnp | grep -E '6566|6570|8815|8888'

# HTTPS responds (Feast UI)
curl -k https://localhost/

# Keycloak OIDC discovery is reachable
curl -k https://localhost/realms/feast-realm/.well-known/openid-configuration | python -m json.tool | head -10
```

---

### Restarting After Changes

```bash
# Stop (data volumes preserved)
docker compose down

# Start again without rebuild
FEAST_HOSTNAME=your.hostname.com docker compose up -d

# Rebuild after Dockerfile or Python file changes
FEAST_HOSTNAME=your.hostname.com docker compose up --build

# If nginx crash-loops after restart (upstream servers not ready yet):
docker restart feast-nginx
```

---

## Part 2 — Client Setup

### Step 1 — Install Python Dependencies

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) then:

```bash
uv sync
```

This installs Feast SDK + all dependencies declared in `pyproject.toml`.

---

### Step 2 — Copy the CA Certificate

```bash
mkdir -p ~/.feast

# From the server machine directly
cp /home/ubuntu/feast-poc-v3/certs/ca.crt ~/.feast/ca.crt

# Or from a remote machine via scp
scp ubuntu@your.hostname.com:/home/ubuntu/feast-poc-v3/certs/ca.crt ~/.feast/ca.crt
```

Verify the cert covers your hostname:
```bash
openssl x509 -noout -text -in ~/.feast/ca.crt | grep -A 3 "Subject Alternative"
# Should show: DNS:your.hostname.com, DNS:localhost, IP Address:127.0.0.1
```

---

### Step 3 — Update `client/feature_store.yaml`

The file already exists in `client/feature_store.yaml`. Update the hostname if you moved to a new EC2 instance:

```yaml
project: credit_risk_modeling
entity_key_serialization_version: 3

registry:
  registry_type: remote
  path: your.hostname.com:443         # ← update this
  cert: /home/ubuntu/feast-poc-v3/certs/ca.crt

offline_store:
  type: remote
  host: your.hostname.com             # ← and this
  port: 443
  scheme: https
  cert: /home/ubuntu/feast-poc-v3/certs/ca.crt

online_store:
  type: remote
  path: https://your.hostname.com:443 # ← and this
  cert: /home/ubuntu/feast-poc-v3/certs/ca.crt
```

> Note: `registry.path` uses `hostname:443` format (not `https://hostname:443`).
> The `https://` prefix causes a port-parsing error in Feast 0.62.0.

---

## Part 3 — Running the Tests

### Test A — End-to-End Connectivity Test (`test_client.py`)

This test authenticates as **alice** (admin role) and verifies all five Feast operations end-to-end.

**Setup (run once per shell session):**
```bash
export FEAST_SERVER_HOST=your.hostname.com
export FEAST_CERT_PATH=/home/ubuntu/feast-poc-v3/certs/ca.crt
envsubst < client/feature_store_alice.yaml > /tmp/fs_alice.yaml
```

**Run:**
```bash
uv run python client/test_client.py
```

What each step verifies:

| Step | Operation | Path Through nginx |
|---|---|---|
| [1] DISCOVER | `list_feature_views()` via registry gRPC | `/feast.registry.*` → 6570 |
| [2] TRAINING | `get_historical_features()` via Arrow Flight | `/arrow.flight.protocol.*` → 8815 |
| [3] SERVING | `get_online_features()` via REST | `/get-online-features` → 6566 |
| [4] CONSISTENCY | Cross-check offline vs online values | Both stores |
| [5] FEATURE SERVICES | `list_feature_services()` via registry gRPC | `/feast.registry.*` → 6570 |

---

### Test B — RBAC + FeatureService Test (`test_rbac.py`)

This is the **main test** — it authenticates as two different users and verifies
that RBAC is enforced correctly across FeatureViews and FeatureServices.

#### Step 1 — Set environment variables

```bash
export FEAST_SERVER_HOST=ec2-16-78-34-107.ap-southeast-3.compute.amazonaws.com
export FEAST_CERT_PATH=/home/ubuntu/feast-poc-v3/certs/ca.crt
```

#### Step 2 — Generate authenticated client configs

The template files (`feature_store_alice.yaml`, `feature_store_bob.yaml`) use
`${FEAST_SERVER_HOST}` and `${FEAST_CERT_PATH}` as placeholders. `envsubst`
replaces them with your environment variables:

```bash
envsubst < client/feature_store_alice.yaml > /tmp/fs_alice.yaml
envsubst < client/feature_store_bob.yaml   > /tmp/fs_bob.yaml
```

Inspect the output to verify substitution worked:
```bash
cat /tmp/fs_alice.yaml | grep -E "path:|host:|cert:|username:"
```

#### Step 3 — Run the test

```bash
uv run python client/test_rbac.py
```

Expected output:

```
============================================================
 TEST 1: alice (admin) — full access
============================================================
  ✓ alice DESCRIBE credit_stats:   customer_credit_stats
  ✓ alice DESCRIBE behavior_stats: customer_behavior_stats

============================================================
 TEST 2: bob (collection_officer) — behavior view only
============================================================
  ✓ bob DESCRIBE behavior_stats:  customer_behavior_stats
  ✓ bob DESCRIBE credit_stats:    correctly blocked (FeastPermissionError)

============================================================
 TEST 3: FeatureService — get_online_features via service bundle
============================================================

  alice (admin):
  ✓ alice → npf_prediction_service (credit + behavior): {npf_flag: [...], ...}
  ✓ alice → collection_strategy_service (behavior only): {avg_monthly_payment: [...], ...}

  bob (collection_officer):
  ✓ bob → collection_strategy_service (behavior only) ✓ allowed: {avg_monthly_payment: [...], ...}
  ✓ bob → npf_prediction_service (contains credit stats) ✗ blocked: correctly blocked (FeastPermissionError)

============================================================
 Results: 8 passed, 0 failed
============================================================
```

#### What TEST 3 is verifying

When bob calls `get_online_features(features=npf_prediction_service)`, Feast:

1. Calls `get_feature_service("npf_prediction_service")` on the registry — **blocked here** because bob's `co-fs-collection-describe` permission uses `name_patterns=["collection_strategy_service"]`, so `npf_prediction_service` doesn't match.
2. If it had passed step 1, it would also be blocked at the FeatureView level (bob has no `READ_ONLINE` on `customer_credit_stats`).

Two independent guards, both enforced.

---

## Part 4 — Understanding RBAC Setup

### How it is Configured

RBAC involves **two files** that must agree on role names:

```
keycloak/realm-export.json          feature_repo/feature_definitions.py
──────────────────────────          ───────────────────────────────────
Defines WHO                         Defines WHAT they can do

roles:
  client:
    feast-app:
      - name: "admin"        ─────► RoleBasedPolicy(roles=["admin"])
      - name: "collection_officer" ► RoleBasedPolicy(roles=["collection_officer"])

users:
  alice → roles: ["admin"]
  bob   → roles: ["collection_officer"]
```

The role name string (e.g., `"admin"`) is the only contract. Case-sensitive.

### Current Permission Matrix

| Permission name | Role | Resource Type | Resource Name | Actions |
|---|---|---|---|---|
| `admin-full-access` | `admin` | FeatureView, Entity | all | CREATE, DESCRIBE, UPDATE, DELETE, READ_ONLINE, READ_OFFLINE, WRITE_ONLINE, WRITE_OFFLINE |
| `co-behavior-read` | `collection_officer` | FeatureView | `customer_behavior_stats` | DESCRIBE, READ_ONLINE, READ_OFFLINE |
| `co-entity-describe` | `collection_officer` | Entity | all | DESCRIBE |
| `admin-fs-access` | `admin` | FeatureService | all | all |
| `co-fs-collection-describe` | `collection_officer` | FeatureService | `collection_strategy_service` | DESCRIBE, READ_ONLINE, READ_OFFLINE |

> **Why does `collection_officer` need Entity DESCRIBE?**
> When Feast resolves a FeatureService for `get_online_features`, it internally
> checks DESCRIBE permission on the Entity type. Without this permission, even
> allowed FeatureService calls fail with a permission error on `Entity/__dummy`.

### How to Add a New User and Role

Adding a new role (e.g., `risk_analyst`) requires changes in two files:

#### 1. `keycloak/realm-export.json`

Add the role:
```json
{
  "name": "risk_analyst",
  "description": "Read both feature views — no write access",
  "composite": false,
  "clientRole": true
}
```

Add the user:
```json
{
  "username": "charlie",
  "email": "charlie@feast.internal",
  "firstName": "Charlie",
  "lastName": "Analyst",
  "enabled": true,
  "emailVerified": true,
  "requiredActions": [],
  "credentials": [{"type": "password", "value": "password123", "temporary": false}],
  "clientRoles": {
    "feast-app": ["risk_analyst"]
  }
}
```

> **Why include email, firstName, lastName, and `emailVerified: true`?**
> Keycloak 26 enables `VERIFY_PROFILE` by default. Users without a complete
> profile are blocked from logging in with error `Account is not fully set up`.

#### 2. `feature_repo/feature_definitions.py`

```python
risk_analyst_permission = Permission(
    name="risk-analyst-read-all",
    policy=RoleBasedPolicy(roles=["risk_analyst"]),
    types=[FeatureView, Entity, FeatureService],
    actions=[AuthzedAction.DESCRIBE, *READ],
)
```

#### 3. Deploy

**Fresh deployment** (Keycloak has never started):
```bash
FEAST_HOSTNAME=your.hostname.com docker compose up --build
```

**Existing deployment** (Keycloak already imported the realm — `realm-export.json` is ignored on restart):
- Use the Keycloak Admin UI at `https://your.hostname.com/realms/master` (admin / admin)
  → Clients → `feast-app` → Roles → add role
  → Users → add user → Role Mappings → assign client role
- Then rebuild to re-run `feast apply`:
  ```bash
  FEAST_HOSTNAME=your.hostname.com docker compose up --build
  ```

### Verifying the JWT Manually

To debug a 403, decode the token at [jwt.io](https://jwt.io). First fetch it:

```bash
curl -s -k -X POST \
  https://your.hostname.com/realms/feast-realm/protocol/openid-connect/token \
  -d "client_id=feast-app&client_secret=feast-secret&username=alice&password=password123&grant_type=password" \
  | python -m json.tool | grep access_token
```

Paste the token at jwt.io and check:
```json
"resource_access": {
  "feast-app": {
    "roles": ["admin"]   ← must match RoleBasedPolicy exactly
  }
}
```

---

## Feature Reference

### Entity

| Name | Type | Description |
|---|---|---|
| `customer_id` | int64 | Multifinance company customer identifier |

### `customer_credit_stats`

Tags: `team: credit_risk`, `model: npf_prediction`

| Feature | Type | Description |
|---|---|---|
| `missed_payments_count` | Int64 | Number of missed payment installments |
| `days_past_due` | Int64 | Maximum days past due on any obligation |
| `outstanding_balance` | Float32 | Total outstanding loan balance (IDR) |
| `credit_utilization_ratio` | Float32 | Used credit / available credit (0–1) |
| `debt_service_ratio` | Float32 | Monthly payment / estimated income (0–2) |
| `loan_to_value_ratio` | Float32 | Outstanding / original loan amount (0–1.2) |
| `npf_flag` | Int64 | 1 = non-performing finance (target label) |

### `customer_behavior_stats`

Tags: `team: credit_risk`, `model: collection_strategy`

| Feature | Type | Description |
|---|---|---|
| `avg_monthly_payment` | Float32 | Average monthly payment amount (IDR) |
| `payment_consistency_score` | Float32 | Regularity of on-time payments (0–1) |
| `tenor_remaining_months` | Int64 | Months remaining on the loan contract |
| `contract_age_months` | Int64 | Months since loan was originated |
| `early_payment_ratio` | Float32 | Fraction of months paid before due date (0–1) |
| `payment_trend_3m` | Float32 | 3-month payment trend (positive = improving) |

### Feature Services

| Service | Views | Features | Access |
|---|---|---|---|
| `npf_prediction_service` | credit (all) + behavior (2) | npf_flag, missed_payments_count, days_past_due, outstanding_balance, credit_utilization_ratio, debt_service_ratio, loan_to_value_ratio, payment_trend_3m, early_payment_ratio | `admin` only |
| `collection_strategy_service` | behavior (all) | avg_monthly_payment, payment_consistency_score, tenor_remaining_months, contract_age_months, early_payment_ratio, payment_trend_3m | `admin` + `collection_officer` |

---

## Troubleshooting

### `401 Unauthenticated` on every request

`test_client.py` requires alice's OIDC config. Run the `envsubst` setup step first:
```bash
export FEAST_SERVER_HOST=your.hostname.com
export FEAST_CERT_PATH=/home/ubuntu/feast-poc-v3/certs/ca.crt
envsubst < client/feature_store_alice.yaml > /tmp/fs_alice.yaml
```
If still failing, verify `docker compose logs feast-keycloak` shows the realm was imported successfully.

To verify a token can be fetched:
```bash
curl -s -k -X POST \
  https://your.hostname.com/realms/feast-realm/protocol/openid-connect/token \
  -d "client_id=feast-app&client_secret=feast-secret&username=alice&password=password123&grant_type=password" \
  | python -m json.tool | grep -E "access_token|error"
```

---

### `Account is not fully set up` (Keycloak 26)

Keycloak 26 enables `VERIFY_PROFILE` by default. Users without email, firstName,
and lastName in their profile cannot log in via the password grant.

**Immediate fix** (existing deployment):
```bash
docker exec feast-keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password admin

docker exec feast-keycloak /opt/keycloak/bin/kcadm.sh update \
  authentication/required-actions/VERIFY_PROFILE -r feast-realm -s enabled=false
```

**Permanent fix** (in `realm-export.json`): ensure every user has `email`, `firstName`,
`lastName`, and `"emailVerified": true` set (see the existing alice/bob entries as a template).

---

### `RS256 requires 'cryptography' to be installed`

The `cryptography` Python package is missing from the Feast Docker image.
The Feast OIDC token parser needs it to verify RS256-signed JWTs from Keycloak.

**Fix:** ensure `"cryptography"` is in the pip install list in `Dockerfile.feast`, then:
```bash
FEAST_HOSTNAME=your.hostname.com docker compose up --build
```

---

### `Hostname Verification Check failed` (gRPC TLS)

The TLS certificate doesn't cover the hostname being used to connect. Common causes:

- **Old cert**: you moved to a new EC2 instance but didn't regenerate the cert
- **Private IP resolution**: from inside EC2, the public hostname resolves to the
  private IP — the cert must cover the hostname (not the IP) for TLS to pass

**Fix:** regenerate the cert for the current hostname:
```bash
bash scripts/gen_certs.sh your.hostname.com
docker restart feast-nginx
```

---

### `Error in service handler!` (gRPC server side)

A gRPC call reached the server but failed inside the handler. Check:
```bash
docker compose logs feast-registry --tail 30
docker compose logs feast-online --tail 30
```

Common causes:
- Missing `cryptography` package (see above)
- Entity permission missing (see below)

---

### `No permissions defined to manage DESCRIBE on Entity/__dummy`

Feast checks `DESCRIBE` permission on `Entity` type when resolving a FeatureService
for `get_online_features`. If no permission covers `Entity`, the call fails even
for users who have `READ_ONLINE` on all required FeatureViews.

**Fix:** add `Entity` to the permission types in `feature_definitions.py`, then re-apply:
```python
# In admin_permission — add Entity to types
types=[FeatureView, Entity],

# For collection_officer — add a separate entity DESCRIBE permission
co_entity_permission = Permission(
    name="co-entity-describe",
    policy=RoleBasedPolicy(roles=["collection_officer"]),
    types=[Entity],
    actions=[AuthzedAction.DESCRIBE],
)
```
Then run `feast apply` (via `docker compose up --build`).

---

### nginx crash-loops on startup (`host not found in upstream`)

nginx resolves `upstream { server hostname:port; }` at startup. If a Feast server
container doesn't exist yet, nginx fails and keeps restarting.

**Fix:** restart nginx after all feast servers are running:
```bash
docker restart feast-nginx
```

To avoid this on future restarts, ensure the startup order in `docker-compose.yml`
is correct (`nginx depends_on` all feast services).

---

### `Failed to parse port in name`

The registry `path` in `feature_store.yaml` has the `https://` prefix:
```yaml
# Wrong
path: https://hostname:443

# Correct
path: hostname:443
```

---

### `403 Permission Denied` (unexpected for allowed user)

1. Decode the JWT at [jwt.io](https://jwt.io) and check `resource_access.feast-app.roles`
2. Verify the role name matches `RoleBasedPolicy` exactly (case-sensitive)
3. Check that the Permission object covers the right `types` (FeatureView vs FeatureService vs Entity)
4. Ensure `feast apply` ran after the Permission was added — permissions are stored in PostgreSQL

---

### Keycloak healthcheck never passing

Keycloak 26.2 (RHEL 9) does not include `curl` or `wget`. The healthcheck in
`docker-compose.yml` uses `bash /dev/tcp` to check if port 8080 is open:

```yaml
test: ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080' 2>/dev/null"]
```

If you see `feast-keycloak` stuck in `health: starting` for more than 2 minutes,
check the logs:
```bash
docker compose logs feast-keycloak | tail -20
```

---

### feast-init stuck or failing

```bash
docker compose logs feast-init
```

Common causes:
- `postgres` or `redis` not healthy yet → wait and retry
- `generate_data.py` error → usually a missing dependency in the Docker image
- `feast apply` failure → syntax error in `feature_definitions.py`

The three servers only start after `feast-init` exits with code 0.
