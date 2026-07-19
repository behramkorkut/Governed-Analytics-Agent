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
import time
from dataclasses import dataclass, field
from typing import cast

import anthropic
from anthropic.types import MessageParam, ToolParam

from . import insights as ins
from . import semantic_layer as sl
from . import verify
from .catalog import Catalog, load_catalog
from .config import settings
from .guardrails import Filter, GuardrailError, MetricQuery, as_str_list, validate
from .pricing import Usage

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
- To restrict to a specific period or segment (e.g. "in May 2026", "for
  France", "completed orders only"), use `filters` — do NOT fetch every period
  and filter in your head. For a single month: dimension=metric_time,
  grain=month, value='2026-05-01' (first day of that month).
- If the question implies a time series, group by metric_time with a grain
  (metric_time__month, metric_time__quarter, metric_time__year).
- If the question cannot be answered with the available metrics/dimensions,
  say so plainly instead of guessing.
- After the tool returns rows, answer concisely in the SAME LANGUAGE as the
  user, citing the actual figures. Round sensibly and add units (currency, %).

ANALYTICAL RIGOR (the figures are authoritative; your commentary must be honest):
- Separate facts from interpretation. The figures come from the governed tool
  and are exact; any "why" or "trend" is YOUR reading — phrase it as such and
  keep it cautious.
- Do not assert correlation or causation from a handful of data points. With
  few categories or short ranges, note that the pattern is only suggestive.
- Beware partial periods. The most recent day/week/month in the data may be
  incomplete; do not call an incomplete period a "decline". Flag it instead.
- State your assumptions. Say which filter you used (e.g. all orders vs only
  completed orders) so the reader knows what the number represents.
- Never compare against a period, segment or benchmark you did not actually
  query. If a comparison is needed, call the tool again to get it.
- USE THE DETERMINISTIC FACTS. When the tool result contains a
  `precomputed_insights` block, those shares, deltas, rankings and coverage
  notes were computed in code and are exact — cite them verbatim. Never
  re-estimate a percentage or a change "by eye"; if a figure you need is not in
  that block, it is fine to call the tool again rather than guess.
- If the request is ambiguous (time range, status filter, grain), state the
  assumption you are making, or ask one short clarifying question.

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
    # Deterministic facts computed from the rows (shares, deltas, coverage),
    # so the model phrases pre-computed numbers instead of estimating them.
    insights: ins.Insights | None = None
    # Figures cited in the answer that are NOT backed by ANY tool call of the
    # run. Empty == every number traces back to some rows/insights the model
    # actually saw (anti-fabrication).
    fabrication_flags: list[str] = field(default_factory=list)
    # Audit evidence: (rows, insights) of EVERY successful tool call, so the
    # anti-fabrication check covers multi-query answers (comparisons), not
    # just the last query.
    evidence: list[tuple[list[dict], ins.Insights | None]] = field(default_factory=list)
    # Observability: what the run cost and how long it took.
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_s: float = 0.0

    @property
    def cost_usd(self) -> float | None:
        return self.usage.cost_usd(self.model)


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
                "filters": {
                    "type": "array",
                    "description": (
                        "Governed filters to restrict the result (preferred over "
                        "fetching everything and filtering mentally). E.g. one month, "
                        "one country, or completed orders only."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {
                                "type": "string",
                                "description": (
                                    "A dimension from the catalog (e.g. "
                                    "customer__country, sales__status, metric_time)."
                                ),
                            },
                            "operator": {
                                "type": "string",
                                "enum": ["=", "!=", ">", ">=", "<", "<=", "in"],
                            },
                            "value": {
                                "description": (
                                    "String/number, or a list for 'in'. For time "
                                    "dims use 'YYYY-MM-DD' (first day of the period)."
                                ),
                            },
                            "grain": {
                                "type": "string",
                                "enum": ["day", "week", "month", "quarter", "year"],
                                "description": (
                                    "Required for time dimensions, e.g. month for a specific month."
                                ),
                            },
                        },
                        "required": ["dimension", "operator", "value"],
                    },
                },
                "limit": {"type": "integer", "description": "Max rows (<=1000)."},
            },
            "required": ["metrics"],
        },
    }


def _tool_input_to_query(data: dict) -> MetricQuery:
    """Build a MetricQuery from raw tool input — defensively.

    The model usually follows the tool schema, but every structural problem
    (missing key, wrong type) must surface as a GuardrailError it can
    self-correct on — never as an unhandled TypeError/KeyError that kills
    the whole run.
    """
    if not isinstance(data, dict):
        raise GuardrailError(f"Tool input must be an object, got {data!r}.")
    raw_filters = data.get("filters") or []
    if not isinstance(raw_filters, list):
        raise GuardrailError(f"'filters' must be a list, got {raw_filters!r}.")
    filters = []
    for f in raw_filters:
        if not isinstance(f, dict):
            raise GuardrailError(f"Each filter must be an object, got {f!r}.")
        missing = [k for k in ("dimension", "operator", "value") if k not in f]
        if missing:
            raise GuardrailError(f"Filter is missing required key(s): {missing}.")
        filters.append(
            Filter(
                dimension=str(f["dimension"]),
                operator=str(f["operator"]),
                value=f["value"],
                grain=f.get("grain"),
            )
        )
    limit = data.get("limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise GuardrailError(f"'limit' must be an integer, got {limit!r}.")
    return MetricQuery(
        metrics=as_str_list(data.get("metrics"), "metrics"),
        group_by=as_str_list(data.get("group_by"), "group_by"),
        order_by=as_str_list(data.get("order_by"), "order_by"),
        filters=filters,
        limit=limit,
    )


class GovernedAnalyticsAgent:
    def __init__(self, catalog: Catalog | None = None, client: anthropic.Anthropic | None = None):
        self.catalog = catalog or load_catalog()
        self.tool = build_tool(self.catalog)
        if client is not None:
            self.client = client
        else:
            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _system(self) -> str:
        return SYSTEM_PROMPT.format(tool=TOOL_NAME, catalog=self.catalog.describe())

    def run(self, question: str) -> AgentResult:
        messages: list[dict] = [{"role": "user", "content": question}]
        result = AgentResult(answer="", model=settings.anthropic_model)
        started = time.perf_counter()

        for _ in range(MAX_STEPS):
            resp = self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                temperature=0,  # deterministic metric routing — governed, repeatable answers
                system=self._system(),
                # The tool schema and message log are built as plain dicts (the
                # metric enum is assembled at runtime); they satisfy the SDK's
                # TypedDicts at runtime, so we narrow the type at the boundary.
                tools=cast("list[ToolParam]", [self.tool]),
                messages=cast("list[MessageParam]", messages),
            )
            result.usage.add(getattr(resp, "usage", None))

            if resp.stop_reason != "tool_use":
                result.answer = "".join(b.text for b in resp.content if b.type == "text").strip()
                return self._finalize(result, started)

            # Echo the assistant turn (required before sending tool_result).
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use" or block.name != TOOL_NAME:
                    continue
                content, is_error = self._execute_tool(block.input, result)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        result.answer = "Stopped after too many steps without a final answer."
        return self._finalize(result, started)

    def _finalize(self, result: AgentResult, started: float) -> AgentResult:
        """Compute the transparency SQL once, for the final query only.

        Kept out of the per-step hot path: the agent may issue several tool
        calls per question, but we only ever need the SQL for the last one.
        """
        if result.query is not None and not result.sql:
            try:
                result.sql = sl.explain_sql(result.query)
            except Exception:  # noqa: BLE001 — transparency is best-effort, never fatal
                result.sql = ""
        # Audit: which cited figures (if any) aren't backed by ANY tool call
        # of the run — a comparison answer legitimately cites several queries.
        result.fabrication_flags = verify.check_answer_multi(result.answer, result.evidence)
        result.latency_s = round(time.perf_counter() - started, 3)
        return result

    def _execute_tool(self, data: dict, result: AgentResult) -> tuple[str, bool]:
        """Validate + run one tool call. Returns (content, is_error)."""
        try:
            query = validate(_tool_input_to_query(data), self.catalog)
        except GuardrailError as e:
            result.steps.append(f"REJECTED {data} -> {e}")
            return f"Guardrail error: {e}", True
        except (TypeError, KeyError, AttributeError) as e:  # belt and braces
            # Malformed tool input must become a tool error the model can
            # self-correct on — never an exception that kills the whole run.
            result.steps.append(f"MALFORMED {data} -> {e}")
            return f"Malformed tool input: {e}", True

        try:
            rows = sl.run_query(query)
        except sl.SemanticLayerError as e:
            result.steps.append(f"EXEC FAILED {query} -> {e}")
            return f"Execution error: {e}", True

        # Remember the last successful query for the UI / transparency.
        # The SQL is resolved once at the end (see _finalize), not per step.
        result.query = query
        result.rows = rows
        result.sql = ""
        result.insights = ins.compute(rows, query)
        # Every successful call feeds the anti-fabrication audit (P4): a
        # multi-query comparison answer may cite figures from any of them.
        result.evidence.append((rows, result.insights))
        result.steps.append(
            f"OK metrics={query.metrics} group_by={query.group_by} -> {len(rows)} rows"
        )
        payload: dict = {"row_count": len(rows), "rows": rows[:MAX_ROWS_TO_MODEL]}
        # Hand the model deterministic, code-computed facts (shares, deltas,
        # data coverage) so it phrases them verbatim instead of estimating.
        summary = ins.summarize(result.insights)
        if summary:
            payload["precomputed_insights"] = summary
        return json.dumps(payload), False


def ask(question: str) -> AgentResult:
    return GovernedAnalyticsAgent().run(question)
