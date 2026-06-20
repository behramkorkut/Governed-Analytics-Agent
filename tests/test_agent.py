"""Tests for the agent: tool schema, arg parsing, and the full loop (mocked LLM)."""

from types import SimpleNamespace as NS

import pytest

from governed_analytics_agent.agent import _tool_input_to_query, build_tool
from governed_analytics_agent.catalog import Catalog, Metric, load_catalog
from governed_analytics_agent.config import settings


def _catalog() -> Catalog:
    return Catalog(
        metrics={"revenue": Metric("revenue", "Revenue", "")},
        dimensions=["product__category", "metric_time"],
        time_dimensions={"metric_time"},
    )


def test_tool_exposes_metric_enum_and_filters():
    schema = build_tool(_catalog())["input_schema"]["properties"]
    assert schema["metrics"]["items"]["enum"] == ["revenue"]
    assert "filters" in schema


def test_tool_input_parses_filters():
    q = _tool_input_to_query(
        {
            "metrics": ["revenue"],
            "filters": [
                {
                    "dimension": "metric_time",
                    "operator": "=",
                    "value": "2026-05-01",
                    "grain": "month",
                }
            ],
        }
    )
    assert q.metrics == ["revenue"]
    assert q.filters[0].dimension == "metric_time"
    assert q.filters[0].grain == "month"


# --- Integration: full tool-use loop with a fake Claude client ------------
needs_warehouse = pytest.mark.skipif(
    not settings.semantic_manifest_path.exists() or not settings.warehouse_db_abs.exists(),
    reason="Build the warehouse and run `dbt parse` first (make warehouse).",
)


class _FakeMessages:
    def __init__(self):
        self.calls = 0

    def create(self, **_):
        self.calls += 1
        if self.calls == 1:
            tool_use = NS(
                type="tool_use",
                name="query_semantic_layer",
                id="t1",
                input={
                    "metrics": ["revenue"],
                    "group_by": ["product__category"],
                    "order_by": ["-revenue"],
                },
            )
            return NS(stop_reason="tool_use", content=[tool_use])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Electronics leads.")])


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


@needs_warehouse
def test_agent_loop_executes_and_answers():
    from governed_analytics_agent.agent import GovernedAnalyticsAgent

    agent = GovernedAnalyticsAgent(catalog=load_catalog(), client=_FakeClient())
    res = agent.run("Revenue by category?")
    assert res.answer == "Electronics leads."
    assert res.query is not None
    assert len(res.rows) == 4  # four product categories
