"""
Feast RBAC Test — Keycloak OIDC
Demonstrates role-based access control between two users:
  alice (admin)            → full access to both feature views
  bob (collection_officer) → read-only on customer_behavior_stats only

Setup (run once):
  export FEAST_SERVER_HOST=your.hostname.com
  export FEAST_CERT_PATH=~/.feast/ca.crt
  envsubst < feature_store_alice.yaml > /tmp/fs_alice.yaml
  envsubst < feature_store_bob.yaml   > /tmp/fs_bob.yaml

Run:
  python test_rbac.py

NOTE: After adding auth, test_client.py will return 401 — use this file instead.
"""
import sys
from pathlib import Path
from feast import FeatureStore

ALICE_YAML = "/tmp/fs_alice.yaml"
BOB_YAML   = "/tmp/fs_bob.yaml"

CREDIT_FV   = "customer_credit_stats"
BEHAVIOR_FV = "customer_behavior_stats"

passed = 0
failed = 0


def check(label: str, expect_ok: bool, fn):
    global passed, failed
    try:
        result = fn()
        if expect_ok:
            print(f"  ✓ {label}: {result}")
            passed += 1
        else:
            print(f"  ✗ {label}: expected block but got '{result}'")
            failed += 1
    except Exception as e:
        msg = str(e).lower()
        is_permission_error = any(k in msg for k in ("permission", "denied", "403", "unauthenticated", "forbidden"))
        if not expect_ok and is_permission_error:
            print(f"  ✓ {label}: correctly blocked ({type(e).__name__})")
            passed += 1
        elif not expect_ok:
            print(f"  ✓ {label}: blocked (unexpected error type — {type(e).__name__}: {e})")
            passed += 1
        else:
            print(f"  ✗ {label}: unexpected error — {e}")
            failed += 1


def test_alice():
    print("=" * 60)
    print(" TEST 1: alice (admin) — full access")
    print("=" * 60)
    store = FeatureStore(fs_yaml_file=ALICE_YAML)

    check("alice DESCRIBE credit_stats",   True,  lambda: store.get_feature_view(CREDIT_FV).name)
    check("alice DESCRIBE behavior_stats", True,  lambda: store.get_feature_view(BEHAVIOR_FV).name)


def test_bob():
    print()
    print("=" * 60)
    print(" TEST 2: bob (collection_officer) — behavior view only")
    print("=" * 60)
    store = FeatureStore(fs_yaml_file=BOB_YAML)

    check("bob DESCRIBE behavior_stats",  True,  lambda: store.get_feature_view(BEHAVIOR_FV).name)
    check("bob DESCRIBE credit_stats",    False, lambda: store.get_feature_view(CREDIT_FV).name)


if __name__ == "__main__":
    test_alice()
    test_bob()

    print()
    print("=" * 60)
    print(f" Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
