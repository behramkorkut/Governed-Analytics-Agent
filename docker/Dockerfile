# Official uv image: Python 3.11 + uv preinstalled (Debian bookworm slim).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# uv settings: copy instead of hardlink (container FS), precompile bytecode.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- Layer 1: dependencies only (cached unless pyproject/lock change) -------
# Copying just the manifests first means `docker build` reuses the installed
# dependencies layer whenever only application code changed -> fast rebuilds.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# --- Layer 2: application code --------------------------------------------
COPY . .
RUN chmod +x docker/entrypoint.sh

# Warehouse + dbt config live inside the container (data is a mounted volume).
ENV WAREHOUSE_DB=/app/data/warehouse.duckdb \
    DBT_PROFILES_DIR=/app/dbt/retail_dwh

EXPOSE 8501

ENTRYPOINT ["/app/docker/entrypoint.sh"]
