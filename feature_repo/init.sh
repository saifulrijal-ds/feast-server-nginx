#!/usr/bin/env bash
# ── Feast 0.62.0 init script ─────────────────────────────────
# Runs once inside feast-init container, then exits.
# All 3 servers start only after this exits with code 0.
set -e

cd /app/feature_repo

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Feast 0.62.0 — Init Bootstrap      ║"
echo "╚══════════════════════════════════════╝"

echo ""
echo "→ [1/3] Generating synthetic Parquet data..."
python /app/feature_repo/generate_data.py

echo ""
echo "→ [2/3] feast apply  (registers features to PostgreSQL registry)..."
feast -c /app/feature_repo apply

echo ""
echo "→ [3/3] feast materialize  (Parquet → Redis online store)..."
# Use ISO8601 format; feast 0.62.0 parses this correctly
START="2020-01-01T00:00:00"
END=$(date -u +"%Y-%m-%dT%H:%M:%S")
feast -c /app/feature_repo materialize "$START" "$END"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Init done. Servers starting now...  ║"
echo "╚══════════════════════════════════════╝"
echo ""
