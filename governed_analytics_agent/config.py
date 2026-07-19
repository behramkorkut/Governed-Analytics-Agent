"""Typed configuration (pydantic-settings).

All runtime config comes from the environment / .env file, never hard-coded.
Paths are resolved as absolutes so that MetricFlow works regardless of the
directory it is invoked from.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# governed_analytics_agent/ -> project root is its parent
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM -------------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # --- REST API ----------------------------------------------------------
    # Optional shared secret gating cost-incurring endpoints (POST /ask).
    # Empty = open access (fine for local dev). SET it before any network
    # exposure: every /ask call triggers billed LLM requests.
    api_token: str = ""

    # --- Cost control ------------------------------------------------------
    # Daily question budget per client IP on the billed surfaces (POST /ask,
    # dashboard chat): beyond it, 429 + Retry-After. 0 disables (local dev).
    rate_limit_per_day: int = 3

    # --- Warehouse / dbt -------------------------------------------------
    warehouse_db: Path = PROJECT_ROOT / "data" / "warehouse.duckdb"
    dbt_project_dir: Path = PROJECT_ROOT / "dbt" / "retail_dwh"

    @property
    def warehouse_db_abs(self) -> Path:
        return (
            self.warehouse_db
            if self.warehouse_db.is_absolute()
            else (PROJECT_ROOT / self.warehouse_db).resolve()
        )

    @property
    def semantic_manifest_path(self) -> Path:
        return self.dbt_project_dir / "target" / "semantic_manifest.json"

    def metricflow_env(self) -> dict[str, str]:
        """Environment needed for the `mf` CLI to find the project + warehouse."""
        return {
            "DBT_PROFILES_DIR": str(self.dbt_project_dir),
            "WAREHOUSE_DB": str(self.warehouse_db_abs),
        }


settings = Settings()
