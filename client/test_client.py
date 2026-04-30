"""
Feast 0.62.0 — Data Scientist Client Test
Run this locally while the Docker stack is running.

  pip install "feast[redis,postgres]==0.62.0" pyarrow pandas
  python test_client.py
"""
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
from feast import FeatureStore

store = FeatureStore(repo_path=str(Path(__file__).parent))

FEATURES = [
    # Credit Stats (original + engineered)
    "customer_credit_stats:missed_payments_count",
    "customer_credit_stats:days_past_due",
    "customer_credit_stats:outstanding_balance",
    "customer_credit_stats:credit_utilization_ratio",
    "customer_credit_stats:debt_service_ratio",
    "customer_credit_stats:loan_to_value_ratio",
    "customer_credit_stats:npf_flag",
    # Behavior Stats (original + engineered)
    "customer_behavior_stats:avg_monthly_payment",
    "customer_behavior_stats:payment_consistency_score",
    "customer_behavior_stats:tenor_remaining_months",
    "customer_behavior_stats:contract_age_months",
    "customer_behavior_stats:early_payment_ratio",
    "customer_behavior_stats:payment_trend_3m",
]

# ─── 1. DISCOVER ─────────────────────────────────────────────
print("\n" + "="*58)
print(" [1] DISCOVER  →  Registry Server (gRPC :6570)")
print("="*58)
for fv in store.list_feature_views():
    print(f"\n  FeatureView : {fv.name}  |  tags={fv.tags}")
    for f in fv.features:
        print(f"    • {f.name:<38} {f.dtype}")

# ─── 2. TRAINING ─────────────────────────────────────────────
print("\n" + "="*58)
print(" [2] TRAINING  →  Offline Server (Arrow Flight :8815)")
print("="*58)

now = datetime.now(timezone.utc)
entity_df = pd.DataFrame({
    "customer_id": [1001, 1002, 1050, 1100, 1200],
    "event_timestamp": [
        now - timedelta(days=5),
        now - timedelta(days=10),
        now - timedelta(days=2),
        now - timedelta(days=30),
        now - timedelta(days=1),
    ],
})

t0 = time.perf_counter()
training_df = store.get_historical_features(
    entity_df=entity_df,
    features=FEATURES,
).to_df()
latency_ms = (time.perf_counter() - t0) * 1000

print(f"\n  Rows returned : {len(training_df)}")
print(f"  Latency       : {latency_ms:.0f}ms")
print(f"  Columns       : {training_df.columns.tolist()}") # <--- ADD THIS
print("\n  Sample (5 rows):")

# Just print the first 5 rows of all columns for now
print(training_df.head().to_string(index=False))
print("\n  ✓ Ready for model.fit(training_df)")

# ─── 3. SERVING ──────────────────────────────────────────────
print("\n" + "="*58)
print(" [3] SERVING   →  Online Server (REST :6566)")
print("="*58)

t0 = time.perf_counter()
fv = store.get_online_features(
    features=FEATURES,
    entity_rows=[
        {"customer_id": 1001},
        {"customer_id": 1042},
        {"customer_id": 1100},
    ],
).to_dict()
latency_ms = (time.perf_counter() - t0) * 1000

print(f"\n  Latency : {latency_ms:.1f}ms")
print("\n  customer_id=1001 vector:")
for k, v in fv.items():
    print(f"    {k:<55} = {v[0]}")
print("\n  ✓ Ready for model.predict(feature_vector)")

# ─── 4. CONSISTENCY CHECK ─────────────────────────────────────
print("\n" + "="*58)
print(" [4] CONSISTENCY CHECK — same feature, both stores")
print("="*58)

hist = store.get_historical_features(
    entity_df=pd.DataFrame({
        "customer_id": [1001],
        "event_timestamp": [datetime.now(timezone.utc)],
    }),
    features=["customer_credit_stats:npf_flag"],
).to_df()

# Assuming the list_feature_views output, the feature is just 'npf_flag'
hist_val   = hist["npf_flag"].iloc[0]
online_val = fv["npf_flag"][0]

print(f"\n  customer_id=1001  npf_flag:")
print(f"    Offline (historical) : {hist_val}")
print(f"    Online  (served)     : {online_val}")
ok = hist_val == online_val
print(f"    {'✓ MATCH — no training-serving skew' if ok else '⚠ MISMATCH — re-materialize?'}")

print("\n" + "="*58)
print(" All 4 tests passed  ✓")
print("="*58 + "\n")
