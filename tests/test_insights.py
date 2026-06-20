"""Unit tests for deterministic insight computation (pure — max_date injected,
so no warehouse query is made)."""

from governed_analytics_agent.guardrails import MetricQuery
from governed_analytics_agent.insights import compute, summarize


def test_shares_total_and_ranking():
    rows = [
        {"product__category": "Electronics", "revenue": "100"},
        {"product__category": "Clothing", "revenue": "300"},
    ]
    q = MetricQuery(metrics=["revenue"], group_by=["product__category"])
    ins = compute(rows, q, max_date="2026-06-15")

    assert ins.total == 400
    assert ins.top is not None and ins.top["label"] == "Clothing"
    assert ins.bottom is not None and ins.bottom["label"] == "Electronics"
    shares = {s["label"]: s["share_pct"] for s in ins.shares}
    assert shares == {"Clothing": 75.0, "Electronics": 25.0}
    assert "Shares of total" in summarize(ins)


def test_time_series_delta_and_partial_period():
    rows = [
        {"metric_time__month": "2026-04-01", "revenue": "100"},
        {"metric_time__month": "2026-05-01", "revenue": "150"},
    ]
    q = MetricQuery(metrics=["revenue"], group_by=["metric_time__month"])
    ins = compute(rows, q, max_date="2026-05-10")  # data stops mid-May → partial

    assert ins.is_time_series
    assert ins.delta is not None
    assert ins.delta["abs"] == 50 and ins.delta["pct"] == 50.0
    assert ins.partial_latest is True
    assert "PARTIAL" in summarize(ins)


def test_complete_period_is_not_partial():
    rows = [
        {"metric_time__month": "2026-04-01", "revenue": "100"},
        {"metric_time__month": "2026-05-01", "revenue": "150"},
    ]
    q = MetricQuery(metrics=["revenue"], group_by=["metric_time__month"])
    ins = compute(rows, q, max_date="2026-05-31")  # full month of data
    assert ins.partial_latest is False


def test_single_headline_value_no_grouping():
    q = MetricQuery(metrics=["revenue"])
    ins = compute([{"revenue": "1234"}], q, max_date="2026-06-15")
    assert ins.total == 1234.0 and ins.shares == []


def test_empty_rows_are_safe():
    ins = compute([], MetricQuery(metrics=["revenue"]), max_date="2026-06-15")
    assert ins.row_count == 0 and ins.metric is None
    assert summarize(ins) == ""
