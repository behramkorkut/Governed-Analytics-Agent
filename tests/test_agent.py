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


# --- Malformed tool input: GuardrailError, never TypeError/KeyError ----------
def test_tool_input_rejects_malformed_filter():
    from governed_analytics_agent.guardrails import GuardrailError

    with pytest.raises(GuardrailError):  # missing required 'dimension' key
        _tool_input_to_query({"metrics": ["revenue"], "filters": [{"operator": "=", "value": "x"}]})


def test_tool_input_rejects_wrong_types():
    from governed_analytics_agent.guardrails import GuardrailError

    with pytest.raises(GuardrailError):  # limit as string
        _tool_input_to_query({"metrics": ["revenue"], "limit": "50"})
    with pytest.raises(GuardrailError):  # metrics not a list
        _tool_input_to_query({"metrics": 42})
    with pytest.raises(GuardrailError):  # non-string metric entry
        _tool_input_to_query({"metrics": ["revenue", 7]})


def test_tool_input_coerces_bare_string_metrics():
    q = _tool_input_to_query({"metrics": "revenue"})
    assert q.metrics == ["revenue"]


def test_execute_tool_returns_tool_error_on_malformed_input():
    """A malformed tool call must come back as an error the model can
    self-correct on — it must never raise and kill the whole run."""
    from governed_analytics_agent.agent import AgentResult, GovernedAnalyticsAgent

    agent = GovernedAnalyticsAgent(catalog=_catalog(), client=_FakeClient())
    res = AgentResult(answer="")
    content, is_error = agent._execute_tool(
        {"metrics": ["revenue"], "filters": [{"operator": "="}]}, res
    )
    assert is_error is True
    assert "Guardrail error" in content or "Malformed" in content


# --- P4: every successful tool call feeds the anti-fabrication audit --------
def test_execute_tool_accumulates_evidence(monkeypatch):
    from governed_analytics_agent import agent as agent_mod
    from governed_analytics_agent.agent import AgentResult, GovernedAnalyticsAgent

    agent = GovernedAnalyticsAgent(catalog=_catalog(), client=_FakeClient())
    monkeypatch.setattr(agent_mod.sl, "run_query", lambda q: [{"revenue": "500"}])
    res = AgentResult(answer="")
    for _ in range(2):
        _, is_error = agent._execute_tool({"metrics": ["revenue"]}, res)
        assert is_error is False
    assert len(res.evidence) == 2
    assert res.evidence[0][0] == [{"revenue": "500"}]


def test_finalize_audits_against_all_tool_calls():
    """A comparison answer citing an EARLIER call's figures must stay clean."""
    from governed_analytics_agent.agent import AgentResult, GovernedAnalyticsAgent

    agent = GovernedAnalyticsAgent(catalog=_catalog(), client=_FakeClient())
    res = AgentResult(answer="France made 500 € while Germany made 800 €.")
    res.evidence = [
        ([{"customer__country": "France", "revenue": "500"}], None),
        ([{"customer__country": "Germany", "revenue": "800"}], None),
    ]
    out = agent._finalize(res, 0.0)
    assert out.fabrication_flags == []
