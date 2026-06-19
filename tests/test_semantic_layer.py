"""Tests for filter compilation (pure) and metric execution (integration)."""

import pytest

from governed_analytics_agent.config import settings
from governed_analytics_agent.guardrails import Filter, MetricQuery
from governed_analytics_agent.semantic_layer import _compile_condition

TIME_DIMS = {"metric_time"}


# --- Pure unit tests (no warehouse) ---------------------------------------
def test_compile_categorical():
    s = _compile_condition(Filter("customer__country", "=", "France"), TIME_DIMS)
    assert "Dimension('customer__country')" in s
    assert s.endswith("= 'France'")


def test_compile_time_uses_timedimension():
    s = _compile_condition(Filter("metric_time", "=", "2026-05-01", "month"), TIME_DIMS)
    assert "TimeDimension('metric_time', 'month')" in s


def test_injection_is_escaped():
    s = _compile_condition(Filter("customer__country", "=", "x' OR '1'='1"), TIME_DIMS)
    # single quotes are doubled -> the payload can't break out of the literal
    assert "x'' OR ''1''=''1" in s


def test_in_operator():
    s = _compile_condition(Filter("product__category", "in", ["Electronics", "Sports"]), TIME_DIMS)
    assert "IN (" in s and "'Electronics'" in s and "'Sports'" in s


# --- Integration (needs a built warehouse + dbt parse) --------------------
needs_warehouse = pytest.mark.skipif(
    not settings.semantic_manifest_path.exists() or not settings.warehouse_db_abs.exists(),
    reason="Build the warehouse and run `dbt parse` first (make warehouse).",
)


@needs_warehouse
def test_run_query_revenue_by_category():
    from governed_analytics_agent import semantic_layer as sl

    rows = sl.run_query(MetricQuery(metrics=["revenue"], group_by=["product__category"]))
    categories = {r["product__category"] for r in rows}
    assert {"Electronics", "Clothing", "Home", "Sports"} <= categories


@needs_warehouse
def test_filter_restricts_results():
    from governed_analytics_agent import semantic_layer as sl

    q = MetricQuery(
        metrics=["revenue"],
        group_by=["customer__country"],
        filters=[Filter("customer__country", "=", "France")],
    )
    rows = sl.run_query(q)
    assert len(rows) == 1 and rows[0]["customer__country"] == "France"
