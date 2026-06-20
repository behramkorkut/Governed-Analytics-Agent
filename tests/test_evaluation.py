"""Unit tests for the eval scorer (pure — no LLM, no warehouse)."""

from governed_analytics_agent.evaluation import EvalCase, accuracy, score_case
from governed_analytics_agent.guardrails import MetricQuery


def test_exact_metric_and_group_by_passes():
    case = EvalCase("revenue by category", ["revenue"], ["product__category"])
    q = MetricQuery(metrics=["revenue"], group_by=["product__category"])
    assert score_case(case, q).passed


def test_wrong_metric_fails():
    s = score_case(EvalCase("revenue", ["revenue"]), MetricQuery(metrics=["orders"]))
    assert not s.passed and not s.metrics_ok


def test_extra_metric_fails_exact_match():
    case = EvalCase("revenue", ["revenue"])
    s = score_case(case, MetricQuery(metrics=["revenue", "orders"]))
    assert not s.metrics_ok


def test_group_by_subset_allows_extra_dimensions():
    case = EvalCase("monthly revenue", ["revenue"], ["metric_time__month"])
    q = MetricQuery(metrics=["revenue"], group_by=["metric_time__month", "product__category"])
    assert score_case(case, q).passed


def test_missing_expected_group_by_fails():
    case = EvalCase("revenue by category", ["revenue"], ["product__category"])
    s = score_case(case, MetricQuery(metrics=["revenue"]))
    assert s.metrics_ok and not s.group_by_ok and not s.passed


def test_none_query_fails():
    assert not score_case(EvalCase("x", ["revenue"]), None).passed


def test_accuracy_empty_and_mixed():
    assert accuracy([]) == 0.0
    good = score_case(EvalCase("a", ["revenue"]), MetricQuery(metrics=["revenue"]))
    bad = score_case(EvalCase("b", ["revenue"]), MetricQuery(metrics=["orders"]))
    assert accuracy([good, bad]) == 0.5
