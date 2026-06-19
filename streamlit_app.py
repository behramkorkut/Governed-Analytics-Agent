"""Governed analytics dashboard (Streamlit).

Two things, one source of truth:
  1) a BI dashboard whose KPIs and charts are computed from the MetricFlow
     semantic layer (not hand-written SQL), and
  2) a chat that routes natural-language questions through the governed agent.

Run:  uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from governed_analytics_agent import reporting
from governed_analytics_agent.catalog import load_catalog
from governed_analytics_agent.config import settings

st.set_page_config(page_title="Governed Analytics", page_icon="📊", layout="wide")


# --- Cached data access (each call shells out to MetricFlow once) ----------
@st.cache_resource
def get_catalog():
    return load_catalog()


@st.cache_data(ttl=600, show_spinner=False)
def fetch(metrics, group_by=None, order_by=None, limit=None) -> pd.DataFrame:
    return reporting.fetch(list(metrics), list(group_by or []), list(order_by or []), limit)


@st.cache_data(ttl=600, show_spinner=False)
def get_kpis() -> dict:
    return reporting.kpis()


@st.cache_resource
def get_agent():
    from governed_analytics_agent.agent import GovernedAnalyticsAgent
    return GovernedAnalyticsAgent(catalog=get_catalog())


def eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


# --- Sidebar ---------------------------------------------------------------
catalog = get_catalog()
with st.sidebar:
    st.header("Governed semantic layer")
    st.caption(
        "Every figure below — KPIs, charts and chat answers — is computed "
        "from the **same** governed metrics (dbt + MetricFlow). No hand-written "
        "SQL, one source of truth."
    )
    st.metric("Codified metrics", len(catalog.metrics))
    st.metric("Dimensions", len(catalog.dimensions))
    with st.expander("Metric catalog"):
        st.code(catalog.describe(), language="text")


st.title("📊 Governed Analytics — Retail")

# --- KPI row ---------------------------------------------------------------
try:
    k = get_kpis()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed revenue", eur(k.get("completed_revenue", 0)))
    c2.metric("Gross margin", f"{k.get('gross_margin_rate', 0) * 100:.1f} %")
    c3.metric("Orders", f"{k.get('orders', 0):,.0f}".replace(",", " "))
    c4.metric("Active customers", f"{k.get('active_customers', 0):,.0f}".replace(",", " "))
except Exception as e:  # noqa: BLE001
    st.error(f"Could not load KPIs (is the warehouse built and dbt parsed?).\n\n{e}")
    st.stop()

st.divider()

# --- Charts ----------------------------------------------------------------
left, right = st.columns(2)

with left:
    st.subheader("Revenue by category")
    df = fetch(("revenue",), ("product__category",), ("-revenue",))
    st.bar_chart(df, x="product__category", y="revenue", color="#4C78A8")

    st.subheader("Return rate by country (%)")
    df = fetch(("return_rate",), ("customer__country",), ("-return_rate",))
    st.bar_chart(df, x="customer__country", y="return_rate", color="#E45756")

with right:
    st.subheader("Revenue by month")
    df = fetch(("revenue",), ("metric_time__month",), ("metric_time__month",))
    st.line_chart(df, x="metric_time__month", y="revenue", color="#54A24B")

    st.subheader("Average order value by channel")
    df = fetch(("average_order_value",), ("sales__channel",), ("-average_order_value",))
    st.bar_chart(df, x="sales__channel", y="average_order_value", color="#72B7B2")

st.divider()

# --- Governed chat ---------------------------------------------------------
st.subheader("💬 Ask the data (governed agent)")
st.caption(
    "The agent maps your question to governed metrics + dimensions and runs "
    "deterministic SQL via MetricFlow. It never invents numbers or SQL."
)

if not settings.anthropic_api_key:
    st.info("Set ANTHROPIC_API_KEY in your .env to enable the chat.")
else:
    if "history" not in st.session_state:
        st.session_state.history = []

    for item in st.session_state.history:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    if prompt := st.chat_input("e.g. Quel pays a le plus fort taux de retour ?"):
        st.session_state.history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Querying the governed semantic layer…"):
                res = get_agent().run(prompt)
            st.markdown(res.answer)
            if res.query:
                with st.expander("How this was computed (transparency)"):
                    st.write(
                        {"metrics": res.query.metrics, "group_by": res.query.group_by,
                         "order_by": res.query.order_by}
                    )
                    if res.rows:
                        st.dataframe(pd.DataFrame(res.rows), width="stretch")
                    if res.sql:
                        st.code(res.sql, language="sql")
        st.session_state.history.append({"role": "assistant", "content": res.answer})
