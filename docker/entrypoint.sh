#!/usr/bin/env bash
# Build the warehouse on first boot, then serve the dashboard.
set -euo pipefail
cd /app

# 1) Build the warehouse only if it does not exist yet (the volume persists it
#    across restarts). Bronze -> Silver -> Gold + dbt tests.
if [ ! -f "$WAREHOUSE_DB" ]; then
  echo "[init] Warehouse not found — building it..."
  uv run python scripts/generate_raw_data.py
  uv run python scripts/load_bronze.py
  uv run dbt build --project-dir dbt/retail_dwh --profiles-dir dbt/retail_dwh
else
  echo "[init] Warehouse found at $WAREHOUSE_DB — skipping build."
fi

# 2) Always (re)generate the semantic manifest the agent/catalog rely on.
( cd dbt/retail_dwh && DBT_PROFILES_DIR="$PWD" uv run dbt parse )

# 3) Serve the requested interface: "api" -> REST API, default -> Streamlit.
MODE="${1:-streamlit}"
if [ "$MODE" = "api" ]; then
  echo "[run] Starting the governed agent REST API on http://localhost:8080 (Swagger: /docs)"
  exec uv run uvicorn governed_analytics_agent.api:app --host 0.0.0.0 --port 8080
fi

echo "[run] Starting Streamlit on http://localhost:8501"
exec uv run streamlit run streamlit_app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true
