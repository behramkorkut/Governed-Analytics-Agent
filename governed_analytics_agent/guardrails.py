"""Validation guardrails for a metric query.

Defence in depth: even though the LLM tool schema only *offers* valid metrics
and dimensions, we re-validate every argument here before execution. Never
trust the model's output blindly — validate against the catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import Catalog

MAX_LIMIT = 1000
TIME_GRAINS = {"day", "week", "month", "quarter", "year"}
OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_VALUE_LEN = 64
# MetricFlow renders the where-clause as a Jinja template BEFORE it reaches
# DuckDB: a value containing template markers would be *evaluated* server-side
# (template injection / DoS via e.g. `{{ range(10**9)|list }}`), not treated as
# a literal. Quote-escaping protects the SQL layer; this protects the template
# layer above it.
JINJA_MARKERS = ("{{", "}}", "{%", "%}")


class GuardrailError(ValueError):
    """Raised when a requested query violates the allow-list / bounds."""


def _dimension_allowed(dim: str, allowed: set[str]) -> bool:
    """A dimension is allowed if it is in the catalog, or if it is a time
    dimension with a trailing grain (e.g. metric_time__month)."""
    if dim in allowed:
        return True
    base, _, grain = dim.rpartition("__")
    return bool(base) and grain in TIME_GRAINS and base in allowed


@dataclass
class Filter:
    """A single governed filter condition (never raw SQL)."""

    dimension: str
    operator: str
    value: object
    grain: str | None = None


@dataclass
class MetricQuery:
    metrics: list[str]
    group_by: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    limit: int | None = None


def as_str_list(value: object, field_name: str) -> list[str]:
    """Coerce a tool argument to a list of strings, or raise GuardrailError.

    The tool schema says arrays, but defence in depth means not depending on
    the model always following it: a malformed argument must produce a
    guardrail error the model can self-correct, never a TypeError/KeyError.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        raise GuardrailError(f"'{field_name}' must be a list of strings, got {value!r}.")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise GuardrailError(f"'{field_name}' entries must be strings, got {item!r}.")
        out.append(item)
    return out


def validate(query: MetricQuery, catalog: Catalog) -> MetricQuery:
    """Return the query unchanged if valid, else raise GuardrailError."""
    # Type checks first: a malformed argument must raise GuardrailError (the
    # model can self-correct on a tool error), never TypeError/KeyError.
    if not isinstance(query.metrics, list) or not all(isinstance(m, str) for m in query.metrics):
        raise GuardrailError(f"'metrics' must be a list of strings, got {query.metrics!r}.")
    if not query.metrics:
        raise GuardrailError("At least one metric is required.")

    unknown_metrics = [m for m in query.metrics if m not in catalog.metrics]
    if unknown_metrics:
        raise GuardrailError(
            f"Unknown metric(s): {unknown_metrics}. Allowed: {catalog.metric_names}"
        )

    allowed_dims = set(catalog.dimensions)
    for d in query.group_by:
        if not _dimension_allowed(d, allowed_dims):
            raise GuardrailError(
                f"Unknown dimension: '{d}'. Allowed: {catalog.dimensions} "
                f"(time dims may take a grain, e.g. metric_time__month)."
            )

    # order_by entries must reference a selected metric or group_by (optionally '-' prefixed)
    selectable = set(query.metrics) | set(query.group_by)
    for o in query.order_by:
        key = o[1:] if o.startswith("-") else o
        if key not in selectable:
            raise GuardrailError(
                f"Cannot order by '{o}': it is not among the selected "
                f"metrics/dimensions {sorted(selectable)}."
            )

    for f in query.filters:
        _validate_filter(f, catalog, allowed_dims)

    if query.limit is not None:
        if isinstance(query.limit, bool) or not isinstance(query.limit, int):
            raise GuardrailError(f"limit must be an integer, got {query.limit!r}.")
        if query.limit <= 0:
            raise GuardrailError("limit must be a positive integer.")
        if query.limit > MAX_LIMIT:
            raise GuardrailError(f"limit must be <= {MAX_LIMIT}.")

    return query


def _validate_filter(f: Filter, catalog: Catalog, allowed_dims: set[str]) -> None:
    if f.dimension not in allowed_dims:
        raise GuardrailError(
            f"Filter on unknown dimension '{f.dimension}'. Allowed: {catalog.dimensions}"
        )
    if f.operator not in OPERATORS:
        raise GuardrailError(f"Unsupported operator '{f.operator}'. Allowed: {sorted(OPERATORS)}")

    if isinstance(f.value, list) and f.operator != "in":
        raise GuardrailError(
            f"Operator '{f.operator}' takes a single value; a list is only valid with 'in'."
        )
    values = f.value if isinstance(f.value, list) else [f.value]
    if not values:
        raise GuardrailError("Filter value cannot be empty.")

    if f.dimension in catalog.time_dimensions:
        if f.grain is not None and f.grain not in TIME_GRAINS:
            raise GuardrailError(f"Invalid time grain '{f.grain}'.")
        for v in values:
            if not DATE_RE.match(str(v)):
                raise GuardrailError(f"Time filter value must be 'YYYY-MM-DD', got '{v}'.")
    else:
        for v in values:
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                raise GuardrailError(f"Invalid filter value: {v!r}.")
            if len(str(v)) > MAX_VALUE_LEN:
                raise GuardrailError("Filter value too long.")
            if isinstance(v, str) and any(m in v for m in JINJA_MARKERS):
                raise GuardrailError(
                    "Filter value contains template markers ({{, }}, {%, %}); "
                    "values are data literals, never templates."
                )
