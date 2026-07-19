"""Tests for the REST serving layer (FastAPI).

Same philosophy as the agent-loop tests: the LLM client is mocked, the
semantic layer is real — so /ask exercises guardrails, MetricFlow compilation
and the anti-fabrication check end to end, with zero API cost.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from governed_analytics_agent.api import app, get_agent
from governed_analytics_agent.config import settings

needs_warehouse = pytest.mark.skipif(
    not settings.semantic_manifest_path.exists() or not settings.warehouse_db_abs.exists(),
    reason="Build the warehouse and run `dbt parse` first (make warehouse).",
)


# --- Fake Claude client: one tool call, then a final answer ----------------
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


@pytest.fixture()
def client():
    """TestClient with the LLM-mocked agent injected as a dependency."""
    from governed_analytics_agent.agent import GovernedAnalyticsAgent
    from governed_analytics_agent.catalog import load_catalog

    agent = GovernedAnalyticsAgent(catalog=load_catalog(), client=_FakeClient())
    app.dependency_overrides[get_agent] = lambda: agent
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- /health: no warehouse, no agent required -------------------------------
def test_health_is_always_up():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body) >= {"warehouse_ready", "semantic_manifest_ready", "model"}


# --- /catalog ----------------------------------------------------------------
@needs_warehouse
def test_catalog_exposes_the_allow_list(client):
    body = client.get("/catalog").json()
    assert "revenue" in body["metrics"]
    assert any("category" in d for d in body["dimensions"])


# --- /ask: full loop against the real semantic layer -------------------------
@needs_warehouse
def test_ask_returns_answer_and_audit_trail(client):
    resp = client.post("/ask", json={"question": "Revenue by category?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Electronics leads."
    assert body["metrics"] == ["revenue"]
    assert body["group_by"] == ["product__category"]
    assert len(body["rows"]) == 4  # four product categories
    assert body["sql"]  # the deterministic proof is exposed
    assert body["fabrication_flags"] == []  # nothing fabricated
    # Mocked LLM responses carry no `usage` block; the tolerant accounting
    # (Usage.add) therefore adds nothing — the structure is still exposed.
    assert set(body["usage"]) == {
        "requests",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
    }
    assert body["usage"]["requests"] == 0


@needs_warehouse
def test_ask_rejects_invalid_payload(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422


# --- Optional API token: /ask is gated when API_TOKEN is configured ---------
@needs_warehouse
def test_ask_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "test-secret")
    payload = {"question": "Revenue by category?"}
    assert client.post("/ask", json=payload).status_code == 401
    assert client.post("/ask", json=payload, headers={"X-API-Key": "wrong"}).status_code == 401
    resp = client.post("/ask", json=payload, headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200


def test_health_stays_open_when_token_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "test-secret")
    assert TestClient(app).get("/health").status_code == 200
