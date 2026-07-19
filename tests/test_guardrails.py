"""Unit tests for the allow-list guardrails (no warehouse required)."""

import pytest

from governed_analytics_agent.catalog import Catalog, Metric
from governed_analytics_agent.guardrails import (
    Filter,
    GuardrailError,
    MetricQuery,
    validate,
)


def _catalog() -> Catalog:
    return Catalog(
        metrics={
            "revenue": Metric("revenue", "Revenue", ""),
            "orders": Metric("orders", "Orders", ""),
        },
        dimensions=["product__category", "customer__country", "metric_time", "sales__status"],
        time_dimensions={"metric_time"},
    )


def test_valid_query_passes():
    q = MetricQuery(metrics=["revenue"], group_by=["product__category"], order_by=["-revenue"])
    assert validate(q, _catalog()) is q


def test_unknown_metric_rejected():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["chiffre_affaire"]), _catalog())


def test_unknown_dimension_rejected():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["revenue"], group_by=["pays"]), _catalog())


def test_time_grain_accepted():
    validate(MetricQuery(metrics=["revenue"], group_by=["metric_time__month"]), _catalog())


def test_order_by_must_be_selected():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["revenue"], order_by=["-orders"]), _catalog())


def test_limit_bounds():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["revenue"], limit=0), _catalog())
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["revenue"], limit=10_000), _catalog())


def test_filter_bad_date_rejected():
    with pytest.raises(GuardrailError):
        validate(
            MetricQuery(metrics=["revenue"], filters=[Filter("metric_time", "=", "may", "month")]),
            _catalog(),
        )


def test_filter_unknown_dimension_rejected():
    with pytest.raises(GuardrailError):
        validate(
            MetricQuery(metrics=["revenue"], filters=[Filter("pays", "=", "France")]),
            _catalog(),
        )


def test_filter_bad_operator_rejected():
    with pytest.raises(GuardrailError):
        validate(
            MetricQuery(metrics=["revenue"], filters=[Filter("customer__country", "LIKE", "Fr%")]),
            _catalog(),
        )


def test_valid_filters_pass():
    q = MetricQuery(
        metrics=["revenue"],
        filters=[
            Filter("metric_time", "=", "2026-05-01", "month"),
            Filter("customer__country", "=", "France"),
        ],
    )
    validate(q, _catalog())


# --- Template-injection regression (MetricFlow renders where-clauses as Jinja) ---
def test_filter_jinja_markers_rejected():
    """A value like '{{ 7*7 }}' would be *evaluated* server-side by MetricFlow's
    Jinja rendering (template injection / DoS via `{{ range(10**9)|list }}`), so
    template markers are refused outright — quote-escaping only covers SQL."""
    for payload in ("{{ 7*7 }}", "{{ range(10**9)|list }}", "{% x %}", "a}}b"):
        with pytest.raises(GuardrailError):
            validate(
                MetricQuery(
                    metrics=["revenue"], filters=[Filter("customer__country", "=", payload)]
                ),
                _catalog(),
            )


def test_filter_jinja_marker_inside_in_list_rejected():
    with pytest.raises(GuardrailError):
        validate(
            MetricQuery(
                metrics=["revenue"],
                filters=[Filter("customer__country", "in", ["France", "{{ 1+1 }}"])],
            ),
            _catalog(),
        )


# --- Malformed input: GuardrailError, never TypeError/KeyError --------------
def test_limit_wrong_type_raises_guardrail_not_typeerror():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics=["revenue"], limit="50"), _catalog())


def test_metrics_wrong_type_raises_guardrail_not_typeerror():
    with pytest.raises(GuardrailError):
        validate(MetricQuery(metrics="revenue"), _catalog())


def test_list_value_with_scalar_operator_rejected():
    with pytest.raises(GuardrailError):
        validate(
            MetricQuery(
                metrics=["revenue"], filters=[Filter("customer__country", "=", ["France"])]
            ),
            _catalog(),
        )
