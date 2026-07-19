"""REST serving layer for the governed agent (FastAPI).

Endpoints:
- GET  /health   : service status (warehouse built? manifest parsed? which model?)
- GET  /catalog  : the governed metrics & dimensions the agent can use
- POST /ask      : natural-language question -> governed answer + full audit trail

Design notes:
- The agent is created lazily (first request) and injected via a FastAPI
  dependency, so tests can substitute an agent built with a mocked LLM client —
  the exact same pattern as the CLI/loop tests.
- The response exposes the whole audit trail (metrics chosen, generated SQL,
  rows, anti-fabrication flags, token cost): the API serves *trustworthy*
  answers, not just answers.
- Cost control: /ask can be gated by an optional shared secret (API_TOKEN env
  var, X-API-Key header), because every question triggers billed LLM calls.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import anthropic
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .agent import GovernedAnalyticsAgent
from .config import settings
from .ratelimit import check_rate_limit

app = FastAPI(
    title="Governed Analytics Agent API",
    version="1.0",
    description=(
        "Ask business questions in plain language; get governed, deterministic "
        "answers computed by the dbt + MetricFlow semantic layer. The LLM routes "
        "to governed metrics — it never writes SQL."
    ),
)


# ---------- Dependency: one agent per process, overridable in tests ----------
@lru_cache(maxsize=1)
def _agent_singleton() -> GovernedAnalyticsAgent:
    return GovernedAnalyticsAgent()  # loads catalog, requires ANTHROPIC_API_KEY


def get_agent() -> GovernedAnalyticsAgent:
    try:
        return _agent_singleton()
    except RuntimeError as exc:  # missing API key / catalog not built
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# FastAPI-recommended dependency style (and bugbear-friendly: no call in defaults).
AgentDep = Annotated[GovernedAnalyticsAgent, Depends(get_agent)]


def verify_token(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Optional shared-secret gate for cost-incurring endpoints.

    Each /ask call can trigger several billed LLM requests, so before the API
    is exposed beyond localhost, set API_TOKEN and require it here. With no
    token configured (local dev), the endpoint stays open.
    """
    if settings.api_token and x_api_key != settings.api_token:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header.")


def _client_ip(request: Request) -> str:
    """Best-effort client IP: first X-Forwarded-For hop when proxied."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    """Daily per-IP budget on billed endpoints: 429 + Retry-After beyond it."""
    allowed, retry_after = check_rate_limit(_client_ip(request), settings.rate_limit_per_day)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily limit reached ({settings.rate_limit_per_day} questions/day/IP) — "
                "each question triggers billed LLM calls."
            ),
            headers={"Retry-After": str(retry_after)},
        )


# ---------- Schemas ----------
class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["Revenue and gross margin by product category in 2026?"],
    )


class UsageOut(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None


class AskResponse(BaseModel):
    answer: str
    # Audit trail: what the agent actually queried, and the deterministic proof.
    metrics: list[str]
    group_by: list[str]
    sql: str
    rows: list[dict[str, Any]]
    # Anti-fabrication: figures cited in the answer with no backing in the data.
    fabrication_flags: list[str]
    # Observability
    model: str
    latency_s: float
    usage: UsageOut


# ---------- Endpoints ----------
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "warehouse_ready": settings.warehouse_db_abs.exists(),
        "semantic_manifest_ready": settings.semantic_manifest_path.exists(),
        "model": settings.anthropic_model,
    }


@app.get("/catalog")
def catalog(agent: AgentDep) -> dict[str, Any]:
    """The governed allow-list: everything the agent is ABLE to query."""
    return {
        "metrics": {m.name: (m.description or m.label) for m in agent.catalog.metrics.values()},
        "dimensions": agent.catalog.dimensions,
    }


@app.post("/ask", response_model=AskResponse)
def ask(
    req: AskRequest,
    agent: AgentDep,
    _token: Annotated[None, Depends(verify_token)],
    _rate: Annotated[None, Depends(rate_limit)],
) -> AskResponse:
    try:
        res = agent.run(req.question)
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc

    return AskResponse(
        answer=res.answer,
        metrics=res.query.metrics if res.query else [],
        group_by=res.query.group_by if res.query else [],
        sql=res.sql,
        rows=res.rows,
        fabrication_flags=res.fabrication_flags,
        model=res.model,
        latency_s=round(res.latency_s, 2),
        usage=UsageOut(
            requests=res.usage.requests,
            input_tokens=res.usage.input_tokens,
            output_tokens=res.usage.output_tokens,
            total_tokens=res.usage.total_tokens,
            cost_usd=res.cost_usd,
        ),
    )


def run() -> None:
    """Entry point for `make api`."""
    uvicorn.run("governed_analytics_agent.api:app", host="0.0.0.0", port=8080)


if __name__ == "__main__":
    run()
