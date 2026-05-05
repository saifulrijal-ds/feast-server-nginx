# ── Multifinance Company Credit Risk Feature Definitions ──────────────
# Two FeatureViews: customer_credit_stats, customer_behavior_stats

from datetime import timedelta
from feast import Entity, FeatureService, FeatureView, Field, FileSource
from feast.permissions.action import AuthzedAction, READ
from feast.permissions.permission import Permission
from feast.permissions.policy import RoleBasedPolicy
from feast.types import Float32, Int64

customer = Entity(
    name="customer_id",
    description="Multifinance Company customer ID",
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

# ── Feature Services ──────────────────────────────────────────
# A FeatureService groups features for a specific model consumption pattern.
# feast apply registers these to the PostgreSQL registry.
# RBAC for get_online_features falls through to per-FeatureView checks.

npf_prediction_service = FeatureService(
    name="npf_prediction_service",
    features=[
        customer_credit_fv,
        customer_behavior_fv[["payment_trend_3m", "early_payment_ratio"]],
    ],
    description="Features for NPF prediction model — credit risk + key payment behavior signals",
    tags={"team": "credit_risk", "model": "npf_prediction"},
)

collection_strategy_service = FeatureService(
    name="collection_strategy_service",
    features=[
        customer_behavior_fv,
    ],
    description="Features for collection strategy model — payment behavior metrics for collection officers",
    tags={"team": "credit_risk", "model": "collection_strategy"},
)

# ── Permissions ───────────────────────────────────────────────
# Roles (defined in Keycloak feast-app client):
#   admin             → alice  — full access to all feature views
#   collection_officer → bob   — read-only on customer_behavior_stats only
#
# AuthzedAction options: CREATE, DESCRIBE, UPDATE, DELETE,
#   READ_ONLINE, READ_OFFLINE, WRITE_ONLINE, WRITE_OFFLINE
# READ = [AuthzedAction.READ_ONLINE, AuthzedAction.READ_OFFLINE]
#
admin_permission = Permission(
    name="admin-full-access",
    policy=RoleBasedPolicy(roles=["admin"]),
    types=[FeatureView, Entity],
    actions=[
        AuthzedAction.CREATE,
        AuthzedAction.DESCRIBE,
        AuthzedAction.UPDATE,
        AuthzedAction.DELETE,
        *READ,
        AuthzedAction.WRITE_ONLINE,
        AuthzedAction.WRITE_OFFLINE,
    ],
)

co_permission = Permission(
    name="co-behavior-read",
    policy=RoleBasedPolicy(roles=["collection_officer"]),
    types=[FeatureView],
    name_patterns=["customer_behavior_stats"],
    actions=[
        AuthzedAction.DESCRIBE,
        *READ,
    ],
)

co_entity_permission = Permission(
    name="co-entity-describe",
    policy=RoleBasedPolicy(roles=["collection_officer"]),
    types=[Entity],
    actions=[AuthzedAction.DESCRIBE],
)

# ── FeatureService Permissions ────────────────────────────────
# Required for list_feature_services() and get_feature_service() via registry gRPC.
# get_online_features() RBAC falls through to FeatureView-level checks above.
#
admin_fs_permission = Permission(
    name="admin-fs-access",
    policy=RoleBasedPolicy(roles=["admin"]),
    types=[FeatureService],
    actions=[
        AuthzedAction.CREATE,
        AuthzedAction.DESCRIBE,
        AuthzedAction.UPDATE,
        AuthzedAction.DELETE,
        *READ,
        AuthzedAction.WRITE_ONLINE,
        AuthzedAction.WRITE_OFFLINE,
    ],
)

co_fs_permission = Permission(
    name="co-fs-collection-describe",
    policy=RoleBasedPolicy(roles=["collection_officer"]),
    types=[FeatureService],
    name_patterns=["collection_strategy_service"],
    actions=[
        AuthzedAction.DESCRIBE,
        *READ,
    ],
)
