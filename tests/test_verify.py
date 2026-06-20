"""Unit tests for the rules-based anti-fabrication check (pure)."""

from governed_analytics_agent.guardrails import MetricQuery
from governed_analytics_agent.insights import compute
from governed_analytics_agent.verify import check_answer

_ROWS = [
    {"product__category": "Electronics", "revenue": "100"},
    {"product__category": "Clothing", "revenue": "300"},
]
_Q = MetricQuery(metrics=["revenue"], group_by=["product__category"])
_INS = compute(_ROWS, _Q, max_date="2026-06-15")  # total 400, Clothing 75%, Electronics 25%


def test_cited_figures_from_data_are_clean():
    answer = "Clothing leads with 300 € (75% of total); Electronics is 100 € (25%)."
    assert check_answer(answer, _ROWS, _INS) == []


def test_fabricated_figure_is_flagged():
    flags = check_answer("Clothing actually made 999 € last quarter.", _ROWS, _INS)
    assert "999" in flags


def test_years_and_small_counts_are_ignored():
    answer = "In 2026 there were 4 product categories and 2 channels."
    assert check_answer(answer, _ROWS, _INS) == []


def test_rounded_restatement_is_tolerated():
    rows = [{"revenue": "1234.56"}]
    # "about 1 235 €" rounds 1234.56 — must not be flagged.
    assert check_answer("Revenue was about 1 235 €.", rows, None) == []


def test_french_decimal_total_is_recognised():
    rows = [{"gross_margin_rate": "0.42"}]
    # FR formatting: "0,42" should match 0.42 in the data.
    assert check_answer("La marge brute est de 0,42.", rows, None) == []
