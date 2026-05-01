"""
Generate enhanced Multifinance Company credit data with realistic correlations.
Uses latent credit_quality variable to create inter-feature dependencies.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import os

SEED = 42
np.random.seed(SEED)
N = 2000  # 4x more customers for richer ML training
OUT = "/app/feature_repo/data"
os.makedirs(OUT, exist_ok=True)

customer_ids = list(range(1001, 1001 + N))

# Latent credit quality per customer (stable across time)
# Beta(4, 1.5): skewed toward good customers (70% have quality > 0.5)
credit_quality = np.random.beta(4, 1.5, N)

credit_rows, behavior_rows = [], []

# 6 snapshots for richer temporal patterns (0, 15, 30, 45, 60, 90 days ago)
for days_ago in [90, 60, 45, 30, 15, 0]:
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)

    # All features derived from credit_quality + noise
    # Poor quality → higher missed payments, days past due, lower consistency

    missed = np.random.poisson(lam=(1 - credit_quality) * 3, size=N).clip(0, 12).astype(int)
    dpd    = (missed * np.random.uniform(10, 45, N) * (1 - credit_quality)).astype(int).clip(0, 180)

    # Outstanding balance: ~5M to 150M IDR, correlated with missed payments
    bal = (np.random.uniform(5_000_000, 150_000_000, N) * (1 + 0.5 * (1 - credit_quality))).round(0)

    # Credit utilization: higher for poor quality customers
    util = (credit_quality * np.random.beta(3, 2, N) + (1 - credit_quality) * 0.6).round(4).clip(0, 1)

    # Debt service ratio (new): payment load relative to assumed income
    # Derived from balance; higher = riskier
    income = 10_000_000 + np.random.uniform(0, 30_000_000, N)
    monthly_payment = bal / (np.random.uniform(24, 48, N))  # 24-48 month tenor
    debt_service_ratio = (monthly_payment / income).round(4).clip(0, 2)

    # Loan-to-value ratio (new): outstanding / original loan amount
    # Assumes some amortization; higher = more risk
    ltv = (0.3 + 0.7 * (1 - credit_quality) + np.random.uniform(-0.1, 0.1, N)).round(4).clip(0, 1.2)

    # NPF flag: customer is non-performing if any risk condition is severe
    npf = (
        (missed >= 2) |                                    # High missed payments
        ((dpd > 90) & (missed >= 1)) |                     # Severe delinquency (>90 DPD) + some missed
        ((debt_service_ratio > 0.65) & (missed >= 1))      # High debt burden + missed
    ).astype(int)

    credit_rows.append(pd.DataFrame({
        "customer_id":               customer_ids,
        "event_timestamp":           ts,
        "missed_payments_count":     missed,
        "days_past_due":             dpd,
        "outstanding_balance":       bal.astype(float),
        "credit_utilization_ratio":  util.astype(float),
        "debt_service_ratio":        debt_service_ratio.astype(float),
        "loan_to_value_ratio":       ltv.astype(float),
        "npf_flag":                  npf,
    }))

    # Behavior features
    avg_pay = (monthly_payment).round(0)

    # Payment consistency: higher quality → more consistent
    consistency = (credit_quality * np.random.beta(6, 2, N) + (1 - credit_quality) * np.random.beta(2, 3, N)).round(4).clip(0, 1)

    tenor_rem = np.random.randint(1, 48, N)
    age = np.random.randint(1, 60, N)

    # Early payment ratio (new): fraction of months paid early
    # High quality → higher early payment rate
    early_payment_ratio = (credit_quality * np.random.beta(3, 2, N)).round(4).clip(0, 1)

    # Payment trend over 3 months (new): positive = improving, negative = worsening
    # Correlated with credit quality + small random walk
    payment_trend = (0.2 * credit_quality - 0.1 * (1 - credit_quality) + np.random.uniform(-0.3, 0.3, N)).round(4).clip(-1, 1)

    behavior_rows.append(pd.DataFrame({
        "customer_id":               customer_ids,
        "event_timestamp":           ts,
        "avg_monthly_payment":       avg_pay.astype(float),
        "payment_consistency_score": consistency.astype(float),
        "tenor_remaining_months":    tenor_rem,
        "contract_age_months":       age,
        "early_payment_ratio":       early_payment_ratio.astype(float),
        "payment_trend_3m":          payment_trend.astype(float),
    }))

df_credit   = pd.concat(credit_rows,   ignore_index=True)
df_behavior = pd.concat(behavior_rows, ignore_index=True)

df_credit.to_parquet(  f"{OUT}/customer_credit_stats.parquet",   index=False)
df_behavior.to_parquet(f"{OUT}/customer_behavior_stats.parquet", index=False)

npf_rate = (df_credit['npf_flag'].sum() / len(df_credit))
print(f"✓ credit   : {len(df_credit):,} rows  → {OUT}/customer_credit_stats.parquet")
print(f"✓ behavior : {len(df_behavior):,} rows → {OUT}/customer_behavior_stats.parquet")
print(f"  customers: {N:,}  |  NPF rate: {npf_rate:.1%}")
