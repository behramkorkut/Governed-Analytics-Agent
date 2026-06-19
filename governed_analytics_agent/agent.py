"""The governed analytics agent (Claude tool-use loop).

Flow:
  question -> Claude picks {metrics, dimensions} via a constrained TOOL
           -> we VALIDATE against the catalog (guardrails)
           -> MetricFlow runs deterministic SQL
           -> Claude writes the final natural-language answer from the rows.

Claude never writes SQL. Its only lever on the warehouse is the tool, whose
arguments are validated before anything runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic

from .catalog import Catalog, load_catalog
from .config import settings
from .guardrails import GuardrailError, MetricQuery, validate
from . import semantic_layer as sl

TOOL_NAME = "query_semantic_layer"
MAX_STEPS = 6
MAX_ROWS_TO_MODEL = 100

SYSTEM_PROMPT = """You are a governed analytics assistant for a retail business.

You answer business questions ONLY by calling the `{tool}` tool, which runs
queries through a governed semantic layer (dbt + MetricFlow). You must NOT
invent numbers and you must NOT write SQL. You can only choose metrics and
dimensions from the catalog below.

Rules:
- Map the user's intent to the closest metric(s) and grouping dimension(s).
- If the question implies a time series, group by metric_time with a grain
  (metric_time__month, metric_time__quarter, metric_time__year).
- If the question cannot be answered with the available metrics/dimensions,
  say so plainly instead of guessing.
- After the tool returns rows, answer concisely in the SAME LANGUAGE as the
  user, citing the actual figures. Round sensibly and add units (currency, %).

CATALOG
-------
{catalog}
"""


@dataclass
class AgentResult:
    answer: str
    query: MetricQuery | None = None
    rows: list[dict] = field(default_factory=list)
    sql: str = ""
    steps: list[str] = field(default_factory=list)


def build_tool(catalog: Catalog) -> dict:
    return {
        "name": TOOL_NAME,
        "description": (
            "Run a governed query against the semantic layer. Choose one or "
            "more metrics and optional grouping dimensions. Returns aggregated "
            "rows. This is the ONLY way to obtain figures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array",
                    "items": {"type": "string", "enum": catalog.metric_names},
                    "description": "One or more metric names from the catalog.",
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Dimensions to group by. Allowed: "
                        + ", ".join(catalog.dimensions)
                        + ". Time dimensions accept a grain, e.g. "
                        "metric_time__month."
                    ),
                },
                "order_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Selected metric/dimension names; prefix '-' for descending.",
                },
                "limit": {"type": "integer", "description": "Max rows (<=1000)."},
            },
            "required": ["metrics"],
        },
    }


def _tool_input_to_query(data: dict) -> MetricQuery:
    return MetricQuery(
        metrics=list(data.get("metrics", [])),
        group_by=list(data.get("group_by", []) or []),
        order_by=list(data.get("order_by", []) or []),
        limit=data.get("limit"),
    )


class GovernedAnalyticsAgent:
    def __init__(self, catalog: Catalog | None = None, client: anthropic.Anthropic | None = None):
        self.catalog = catalog or load_catalog()
        self.tool = build_tool(self.catalog)
        if client is not None:
            self.client = client
        else:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Add it to your .env file."
                )
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _system(self) -> str:
        return SYSTEM_PROMPT.format(tool=TOOL_NAME, catalog=self.catalog.describe())

    def run(self, question: str) -> AgentResult:
        messages: list[dict] = [{"role": "user", "content": question}]
        result = AgentResult(answer="")

        for _ in range(MAX_STEPS):
            resp = self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                system=self._system(),
                tools=[self.tool],
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                result.answer = "".join(
                    b.text for b in resp.content if b.type == "text"
                ).strip()
                return result

            # Echo the assistant turn (required before sending tool_result).
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use" or block.name != TOOL_NAME:
                    continue
                content, is_error = self._execute_tool(block.input, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})

        result.answer = "Stopped after too many steps without a final answer."
        return result

    def _execute_tool(self, data: dict, result: AgentResult) -> tuple[str, bool]:
        """Validate + run one tool call. Returns (content, is_error)."""
        try:
            query = validate(_tool_input_to_query(data), self.catalog)
        except GuardrailError as e:
            result.steps.append(f"REJECTED {data} -> {e}")
            return f"Guardrail error: {e}", True

        try:
            rows = sl.run_query(query)
        except sl.SemanticLayerError as e:
            result.steps.append(f"EXEC FAILED {query} -> {e}")
            return f"Execution error: {e}", True

        # Remember the last successful query for the UI / transparency.
        result.query = query
        result.rows = rows
        try:
            result.sql = sl.explain_sql(query)
        except Exception:
            result.sql = ""
        result.steps.append(
            f"OK metrics={query.metrics} group_by={query.group_by} -> {len(rows)} rows"
        )
        payload = rows[:MAX_ROWS_TO_MODEL]
        return json.dumps({"row_count": len(rows), "rows": payload}), False


def ask(question: str) -> AgentResult:
    return GovernedAnalyticsAgent().run(question)
