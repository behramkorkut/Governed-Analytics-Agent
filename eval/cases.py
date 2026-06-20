"""Labelled routing cases: a question and the metric selection a correct agent
should make. Mixed FR/EN on purpose — the agent answers in the user's language,
and routing must be language-agnostic. Keep `expect_metrics` to what the question
unambiguously asks for; leave `expect_group_by` empty when no grouping is implied.
"""

from __future__ import annotations

from governed_analytics_agent.evaluation import EvalCase

CASES: list[EvalCase] = [
    EvalCase("Revenue by product category", ["revenue"], ["product__category"]),
    EvalCase("Quel est le chiffre d'affaires total ?", ["revenue"]),
    EvalCase("What is the return rate by country?", ["return_rate"], ["customer__country"]),
    EvalCase(
        "Average order value by sales channel",
        ["average_order_value"],
        ["sales__channel"],
    ),
    EvalCase("Show me the monthly revenue trend", ["revenue"], ["metric_time__month"]),
    EvalCase("Combien de clients actifs avons-nous ?", ["active_customers"]),
    EvalCase(
        "Gross margin rate by product category",
        ["gross_margin_rate"],
        ["product__category"],
    ),
    EvalCase("Combien de commandes par canal de vente ?", ["orders"], ["sales__channel"]),
    EvalCase("What share of customers are repeat buyers?", ["repeat_customer_rate"]),
]
