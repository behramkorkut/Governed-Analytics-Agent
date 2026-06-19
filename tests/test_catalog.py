"""Catalog loading from the semantic manifest (integration: needs dbt parse)."""

import pytest

from governed_analytics_agent.catalog import load_catalog
from governed_analytics_agent.config import settings

needs_manifest = pytest.mark.skipif(
    not settings.semantic_manifest_path.exists(),
    reason="Run `dbt parse` first (make parse).",
)


@needs_manifest
def test_catalog_has_expected_metrics_and_dimensions():
    cat = load_catalog()
    assert "revenue" in cat.metrics
    assert len(cat.metrics) >= 12
    assert "product__category" in cat.dimensions
    assert "metric_time" in cat.time_dimensions
