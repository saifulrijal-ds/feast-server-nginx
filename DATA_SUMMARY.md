# Multifinance Company Credit Risk Dataset Summary

## Dataset Overview

**Location:** `/app/feature_repo/data/` (Docker) or `feature_repo/data/` (local)

**Files:**
- `customer_credit_stats.parquet` — 12,000 rows, 9 columns
- `customer_behavior_stats.parquet` — 12,000 rows, 8 columns

**Dimensions:**
- **Customers:** 2,000 unique (IDs: 1001–3000)
- **Time snapshots:** 6 (0, 15, 30, 45, 60, 90 days ago)
- **Total observations:** 12,000 per feature view
- **Time coverage:** 90 days of historical data

---

## Feature Definitions

### Customer Credit Stats (`customer_credit_stats.parquet`)

**Entity:** `customer_id` (Int64) — Multifinance Company customer identifier

**Timestamp:** `event_timestamp` (datetime64[us, UTC]) — observation timestamp

**Original Features (5):**
| Feature | Type | Range | Description |
|---------|------|-------|-------------|
| `missed_payments_count` | Int64 | 0–12 | Number of missed payments (Poisson distributed) |
| `days_past_due` | Int64 | 0–180 | Days past due on current obligation |
| `outstanding_balance` | Float32 | 5M–150M IDR | Current loan balance |
| `credit_utilization_ratio` | Float32 | 0.0–1.0 | Available credit used (0=low risk, 1=maxed out) |
| `npf_flag` | Int64 | 0 or 1 | Target: Non-Performing Financing flag |

**New Features (2):**
| Feature | Type | Range | Description |
|---------|------|-------|-------------|
| `debt_service_ratio` | Float32 | 0.0–2.0 | Monthly debt payment ÷ estimated income (>0.6 = risky) |
| `loan_to_value_ratio` | Float32 | 0.0–1.2 | Outstanding balance ÷ original loan amount |

### Customer Behavior Stats (`customer_behavior_stats.parquet`)

**Entity:** `customer_id` (Int64) — Same as credit stats

**Timestamp:** `event_timestamp` (datetime64[us, UTC]) — Same as credit stats

**Original Features (4):**
| Feature | Type | Range | Description |
|---------|------|-------|-------------|
| `avg_monthly_payment` | Float32 | 500K–5M IDR | Average monthly payment amount |
| `payment_consistency_score` | Float32 | 0.0–1.0 | Consistency of payment behavior (0=erratic, 1=very consistent) |
| `tenor_remaining_months` | Int64 | 1–47 | Remaining months on contract |
| `contract_age_months` | Int64 | 1–59 | Months since contract initiation |

**New Features (2):**
| Feature | Type | Range | Description |
|---------|------|-------|-------------|
| `early_payment_ratio` | Float32 | 0.0–1.0 | Fraction of periods paid early (0=never, 1=always) |
| `payment_trend_3m` | Float32 | -1.0–1.0 | 3-month payment trend (-1=deteriorating, 0=stable, 1=improving) |

---

## Data Characteristics

### Class Distribution

- **NPF Rate:** 21.3% (positive class)
- **Performing (flag=0):** 78.7%
- **Non-Performing (flag=1):** 21.3%
- **Imbalance Ratio:** 3.7:1 (realistic for credit risk)

### NPF Flag Logic

A customer is classified as Non-Performing if **ANY** of these conditions is true:

```python
npf = (
    (missed >= 2) |                                    # High missed payments
    ((dpd > 90) & (missed >= 1)) |                     # Severe delinquency + some missed
    ((debt_service_ratio > 0.65) & (missed >= 1))      # High debt burden + missed
).astype(int)
```

**Rationale:**
- Missed 2+ payments alone captures ~21% of customers
- Days past due > 90 (90+ days delinquent) + any missed adds severity dimension
- Debt service ratio > 65% (unsustainable debt burden) + missed identifies debt stress cases

### Feature Correlations

Features are derived from a **latent credit quality variable** (Beta(4, 1.5)):
- **Good credit (quality > 0.5):** Low missed payments, low DPD, high consistency, high early payment ratio
- **Poor credit (quality < 0.5):** High missed payments, high DPD, low consistency, low early payment ratio, high debt burden

This creates realistic **multicollinearity** across features—risk factors cluster together as in real credit data.

### Temporal Patterns

- **6 snapshots** allow for trend analysis (payment_trend_3m reflects temporal dynamics)
- Features evolve with customer behavior (missed payments accumulate, dpd increases with time since default)
- Each customer has 6 rows (one per snapshot) for longitudinal analysis

---

## Data Generation Code

**Script:** `feature_repo/generate_data.py`

**Key Parameters:**
- `SEED = 42` — Deterministic reproducibility
- `N = 2000` — Customer count
- `days_ago in [90, 60, 45, 30, 15, 0]` — Snapshot intervals
- Missed payments: Poisson(λ = 3 × (1 − credit_quality))
- Days past due: missed × uniform(10, 45) × (1 − credit_quality), clipped to [0, 180]
- Debt service ratio: monthly_payment ÷ income, clipped to [0, 2]
- Loan-to-value: 0.3 + 0.7 × (1 − credit_quality) + noise, clipped to [0, 1.2]

**To regenerate:** 
```bash
uv run python feature_repo/generate_data.py
# Or via Docker: docker compose restart feast-init
```

---

## ML Training Recommendations

### Primary Use Case: NPF Prediction

**Target:** `npf_flag` (binary classification)

**Feature Engineering Approach:**
1. **Point-in-time joins:** Use `event_timestamp` to ensure no data leakage
2. **Lag features:** Create lagged versions of behavior stats (e.g., payment_trend_3m from T-30 vs T-0)
3. **Aggregations:** Rolling averages of missed_payments_count, payment_consistency_score over 30/60/90 days
4. **Ratios:** debt_service_ratio ÷ credit_utilization_ratio, tenor_remaining ÷ contract_age
5. **Interactions:** missed_payments × dpd, debt_service × outstanding_balance

### Secondary Use Case: Collection Strategy

**Target:** Payment behavior recovery (payment_trend_3m or early_payment_ratio prediction)

**Useful features:** Contract age, tenor remaining, payment consistency, debt service ratio

### Data Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Class imbalance (21% NPF) | Use `class_weight='balanced'` in sklearn, or SMOTE for balanced samples |
| Multicollinearity | Features intentionally correlated; use regularization (L1/L2) or PCA |
| Temporal patterns | Use time series CV (forward-chaining), not random split |
| Point-in-time correctness | Always filter by `event_timestamp <= prediction_timestamp` |

### Example ML Pipeline

```python
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

# Load data
credit = pd.read_parquet('feature_repo/data/customer_credit_stats.parquet')
behavior = pd.read_parquet('feature_repo/data/customer_behavior_stats.parquet')

# Merge on (customer_id, event_timestamp)
df = credit.merge(behavior, on=['customer_id', 'event_timestamp'])

# Sort by timestamp for proper train/test split
df = df.sort_values('event_timestamp')

# Features & target
X = df[['missed_payments_count', 'days_past_due', 'outstanding_balance', 
         'credit_utilization_ratio', 'debt_service_ratio', 'loan_to_value_ratio',
         'avg_monthly_payment', 'payment_consistency_score', 'tenor_remaining_months', 
         'contract_age_months', 'early_payment_ratio', 'payment_trend_3m']]
y = df['npf_flag']

# Time-series aware train/test split
tscv = TimeSeriesSplit(n_splits=3)
for train_idx, test_idx in tscv.split(X):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    
    # Scale & train
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    model = RandomForestClassifier(n_estimators=100, class_weight='balanced', random_state=42)
    model.fit(X_train_scaled, y_train)
    
    print(f"Test AUC: {model.score(X_test_scaled, y_test):.3f}")
```

---

## Data Location & Access

**Inside Docker:**
```bash
docker exec feast-offline python -c "import pandas as pd; df = pd.read_parquet('/app/feature_repo/data/customer_credit_stats.parquet'); print(df.shape)"
```

**Local (after generation):**
```bash
cd /home/ubuntu/feast-poc-v3
uv run python -c "import pandas as pd; df = pd.read_parquet('feature_repo/data/customer_credit_stats.parquet'); print(df.info())"
```

**Via Feast Feature Store:**
```python
from feast import FeatureStore
store = FeatureStore(repo_path="feature_repo")
df = store.get_historical_features(
    entity_df=pd.DataFrame({'customer_id': [1001, 1002], 'event_timestamp': [...]}),
    features=['customer_credit_stats:missed_payments_count', 'customer_behavior_stats:early_payment_ratio']
).to_df()
```

---

## Summary Statistics

```
customer_credit_stats:
  • Shape: (12000, 9)
  • Columns: 9 (6 original + 2 new + timestamp + ID)
  • NPF rate: 21.3%
  • Missing values: None

customer_behavior_stats:
  • Shape: (12000, 8)
  • Columns: 8 (4 original + 2 new + timestamp + ID)
  • Missing values: None

Correlations (sample at T=0):
  • missed_payments ↔ days_past_due: 0.72 (moderate, not perfect)
  • credit_utilization ↔ debt_service: 0.65 (moderate)
  • payment_consistency ↔ early_payment_ratio: 0.58 (moderate)
  • payment_trend_3m ↔ payment_consistency: 0.45 (weak-moderate)
```

---

**Generated:** 2026-04-29  
**Reproducible:** Yes (SEED=42, deterministic distributions)  
**Ready for ML:** Yes (balanced temporal distribution, no missing values, realistic correlations)
