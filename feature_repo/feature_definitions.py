# ── BFI Finance Credit Risk Feature Definitions ──────────────
# Two FeatureViews: customer_credit_stats, customer_behavior_stats

from datetime import timedelta
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int64

customer = Entity(
    name="customer_id",
    description="BFI Finance customer ID",
)

credit_source = FileSource(
    name="customer_credit_stats_source",
    path="/app/feature_repo/data/customer_credit_stats.parquet",
    timestamp_field="event_timestamp",
)

behavior_source = FileSource(
    name="customer_behavior_stats_source",
    path="/app/feature_repo/data/customer_behavior_stats.parquet",
    timestamp_field="event_timestamp",
)

customer_credit_fv = FeatureView(
    name="customer_credit_stats",
    entities=[customer],
    ttl=timedelta(days=90),
    schema=[
        Field(name="missed_payments_count",    dtype=Int64),
        Field(name="days_past_due",            dtype=Int64),
        Field(name="outstanding_balance",      dtype=Float32),
        Field(name="credit_utilization_ratio", dtype=Float32),
        Field(name="debt_service_ratio",       dtype=Float32),
        Field(name="loan_to_value_ratio",      dtype=Float32),
        Field(name="npf_flag",                 dtype=Int64),
    ],
    source=credit_source,
    tags={"team": "credit_risk", "model": "npf_prediction"},
)

customer_behavior_fv = FeatureView(
    name="customer_behavior_stats",
    entities=[customer],
    ttl=timedelta(days=90),
    schema=[
        Field(name="avg_monthly_payment",        dtype=Float32),
        Field(name="payment_consistency_score",  dtype=Float32),
        Field(name="tenor_remaining_months",     dtype=Int64),
        Field(name="contract_age_months",        dtype=Int64),
        Field(name="early_payment_ratio",        dtype=Float32),
        Field(name="payment_trend_3m",           dtype=Float32),
    ],
    source=behavior_source,
    tags={"team": "credit_risk", "model": "collection_strategy"},
)
