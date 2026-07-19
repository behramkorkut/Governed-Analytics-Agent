"""Unit tests for the rules-based anti-fabrication check (pure)."""

from governed_analytics_agent.guardrails import MetricQuery
from governed_analytics_agent.insights import compute
from governed_analytics_agent.verify import check_answer, check_answer_multi

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


def test_ratio_restated_as_percent_is_recognised():
    rows = [
        {"product__category": "Electronics", "gross_margin_rate": "0.2350480059"},
        {"product__category": "Clothing", "gross_margin_rate": "0.3237678786"},
    ]
    answer = "Electronics margin is 23.5% while Clothing reaches 32.4%."
    assert check_answer(answer, rows, None) == []


def test_column_total_is_recognised():
    # 480336.6 + 217780.98 + 151116.54 + 95278.97 = 944513.09
    rows = [
        {"c": "Electronics", "revenue": "480336.6"},
        {"c": "Sports", "revenue": "217780.98"},
        {"c": "Home", "revenue": "151116.54"},
        {"c": "Clothing", "revenue": "95278.97"},
    ]
    assert check_answer("Total revenue reached $944,513.", rows, None) == []


def test_wrong_percent_and_wrong_total_are_still_flagged():
    rows = [
        {"c": "A", "revenue": "100", "rate": "0.235"},
        {"c": "B", "revenue": "300", "rate": "0.32"},
    ]
    flags = check_answer("The margin is 28.0% and the total is 950 \u20ac.", rows, None)
    assert "28.0" in flags
    assert any("950" in f for f in flags)


# --- Multi-query audit (P4): evidence from EVERY tool call counts -----------
def test_multi_query_answer_is_audited_against_all_calls():
    """A comparison answer cites figures from several governed queries: a
    figure backed by an EARLIER call must not be flagged as fabricated."""
    call_1 = ([{"customer__country": "France", "revenue": "500"}], None)
    call_2 = ([{"customer__country": "Germany", "revenue": "800"}], None)
    answer = "France made 500 € while Germany made 800 €."
    # Against the last call only, 500 would be (wrongly) flagged:
    assert "500" in check_answer(answer, *call_2)
    # Against all calls, the answer is fully backed:
    assert check_answer_multi(answer, [call_1, call_2]) == []


def test_multi_query_still_flags_truly_fabricated_figures():
    call_1 = ([{"revenue": "500"}], None)
    call_2 = ([{"revenue": "800"}], None)
    assert "999" in check_answer_multi("Revenue was 999 €.", [call_1, call_2])
