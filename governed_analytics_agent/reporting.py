"""Reporting helpers: pull governed metrics from the semantic layer as
pandas DataFrames. The BI dashboard uses these, so dashboards and the agent
share the exact same metric definitions (one source of truth).
"""

from __future__ import annotations

import pandas as pd

from .guardrails import MetricQuery
from . import semantic_layer as sl


def fetch(
    metrics: list[str],
    group_by: list[str] | None = None,
    order_by: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Run a metric query and return a DataFrame with numeric metric columns."""
    q = MetricQuery(
        metrics=metrics,
        group_by=group_by or [],
        order_by=order_by or [],
        limit=limit,
    )
    rows = sl.run_query(q)
    df = pd.DataFrame(rows)
    for m in metrics:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce")
    return df


def kpis() -> dict[str, float]:
    """Headline KPIs as a single-row fetch (no grouping)."""
    df = fetch(["completed_revenue", "gross_margin_rate", "orders", "active_customers"])
    if df.empty:
        return {}
    row = df.iloc[0]
    return {
        "completed_revenue": float(row.get("completed_revenue", 0) or 0),
        "gross_margin_rate": float(row.get("gross_margin_rate", 0) or 0),
        "orders": float(row.get("orders", 0) or 0),
        "active_customers": float(row.get("active_customers", 0) or 0),
    }
