"""Integration tests for the BI reporting helpers (need a built warehouse)."""

import pytest

from governed_analytics_agent.config import settings

needs_warehouse = pytest.mark.skipif(
    not settings.semantic_manifest_path.exists() or not settings.warehouse_db_abs.exists(),
    reason="Build the warehouse and run `dbt parse` first (make warehouse).",
)


@needs_warehouse
def test_kpis_returns_headline_numbers():
    from governed_analytics_agent import reporting

    k = reporting.kpis()
    assert set(k) >= {"completed_revenue", "gross_margin_rate", "orders", "active_customers"}
    assert k["orders"] > 0


@needs_warehouse
def test_fetch_coerces_metric_columns_to_numeric():
    from governed_analytics_agent import reporting

    df = reporting.fetch(["revenue"], ["product__category"])
    assert "revenue" in df.columns
    assert df["revenue"].dtype.kind in "fi"  # numeric, not object/string
    assert len(df) == 4
