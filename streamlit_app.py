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
from governed_analytics_agent.freshness import read_freshness
from governed_analytics_agent.ratelimit import check_rate_limit

# Freshness SLA for the near-real-time lane (matches the dbt test default).
RT_SLA_SECONDS = 120

st.set_page_config(page_title="Governed Analytics", page_icon="", layout="wide")


# --- First-boot bootstrap --------------------------------------------------
# On a fresh deploy (e.g. Streamlit Community Cloud) the warehouse isn't built
# yet — the DuckDB file and semantic manifest are generated artifacts, never
# committed. Build them once, with the same pipeline as `make warehouse` and the
# Docker entrypoint. A no-op locally / in Docker, where the warehouse exists.
@st.cache_resource(show_spinner="First boot: building the warehouse (~30s)…")
def _ensure_warehouse() -> bool:
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    from governed_analytics_agent.config import PROJECT_ROOT

    if settings.semantic_manifest_path.exists() and settings.warehouse_db_abs.exists():
        return True

    env = {
        **os.environ,
        "WAREHOUSE_DB": str(settings.warehouse_db_abs),
        "DBT_PROFILES_DIR": str(settings.dbt_project_dir),
    }
    # Each step runs in its OWN process so the DuckDB file lock is released
    # before MetricFlow (also a subprocess) queries it. An in-process dbt build
    # would keep the warehouse locked by the Streamlit process and every `mf`
    # call would then fail with a DuckDB "conflicting lock" error.
    dbt = shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")
    project = str(settings.dbt_project_dir)
    steps = [
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_raw_data.py")],
        # load_bronze imports the package (landing-table DDL), so run it as a
        # module with the project root on sys.path.
        [sys.executable, "-m", "scripts.load_bronze"],
        [dbt, "build", "--project-dir", project, "--profiles-dir", project],
        [dbt, "parse", "--project-dir", project, "--profiles-dir", project],
    ]
    for cmd in steps:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Warehouse build step failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}"
            )
    return True


_ensure_warehouse()


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


def render_answer(res) -> None:
    """Render one governed answer: 📖 Reading (LLM) vs 🔢 Figures (deterministic)."""
    st.markdown("**📖 Lecture** _(interprétation du modèle)_")
    st.markdown(res.answer)
    if not res.query:
        return

    ins = res.insights
    if ins and ins.partial_latest:
        st.warning(
            "⚠️ La dernière période est **partielle** (données incomplètes) — "
            "ne pas l'interpréter comme une baisse."
        )

    # Deterministic + auditable: same source of truth as the KPIs, never the LLM.
    with st.container(border=True):
        st.markdown("**🔢 Chiffres** _(déterministe, auditable)_")
        if ins and ins.delta:
            d = ins.delta
            delta = f"{d['abs']:+,.0f}"
            if d["pct"] is not None:
                delta += f" ({d['pct']:+}%)"
            st.metric(f"{ins.metric} — {d['latest']}", f"{d['latest_value']:,.0f}", delta)
        if res.rows:
            st.dataframe(pd.DataFrame(res.rows), width="stretch")
        with st.expander("Métriques, dimensions & SQL généré"):
            st.write(
                {
                    "metrics": res.query.metrics,
                    "group_by": res.query.group_by,
                    "order_by": res.query.order_by,
                }
            )
            if res.sql:
                st.code(res.sql, language="sql")
        if res.fabrication_flags:
            st.caption(
                "⚠️ Chiffres cités non retrouvés dans les données : "
                + ", ".join(res.fabrication_flags)
            )
        else:
            st.caption("✓ Tous les chiffres cités figurent dans les données.")

    cost = res.cost_usd
    cost_txt = f"${cost:.4f}" if cost is not None else "n/a"
    st.caption(
        f"⏱ {res.latency_s:.1f}s · {res.usage.total_tokens:,} tokens · {cost_txt} · {res.model}"
    )


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


st.markdown(
    """
    <style>
      /* KPI + figure cards: subtle terracotta-tinted panels */
      [data-testid="stMetric"] {
        background: rgba(217, 119, 87, 0.07);
        border: 1px solid rgba(217, 119, 87, 0.22);
        border-radius: 14px;
        padding: 14px 16px;
      }
      /* Example-question chips */
      .stButton > button {
        border-radius: 999px;
        border: 1px solid rgba(217, 119, 87, 0.40);
        background: rgba(217, 119, 87, 0.08);
        font-weight: 500;
      }
      .stButton > button:hover {
        border-color: #D97757;
        background: rgba(217, 119, 87, 0.18);
      }
    </style>
    <div style="background: linear-gradient(135deg, #D97757 0%, #B5471F 100%);
                padding: 1.5rem 1.8rem; border-radius: 18px; margin-bottom: 1.3rem;
                box-shadow: 0 6px 24px rgba(217, 119, 87, 0.28);">
      <h1 style="color: #fff; margin: 0; font-size: 2.05rem; font-weight: 700;
                 letter-spacing: -0.5px;">Governed Analytics — Retail</h1>
      <p style="color: #fdeee7; margin: 0.45rem 0 0; font-size: 1.02rem;">
        One governed semantic layer — every KPI, chart and chat answer is computed
        from the <b>same</b> metrics. No hand-written SQL, one source of truth.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

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


# --- Live (near-real-time) panel -------------------------------------------
# Same governed metrics as the batch KPIs above, but on the streaming lane
# (fact_sales_live / sales_live). Short cache TTL so it actually feels live;
# freshness is read from the rt_freshness view, evaluated at query time.
@st.cache_data(ttl=10, show_spinner=False)
def get_live() -> dict:
    # Call reporting.fetch directly (not the 600s-cached dashboard `fetch`) so the
    # live panel honours its own short TTL.
    df = reporting.fetch(["revenue_live", "orders_live"])
    row = df.iloc[0].to_dict() if not df.empty else {}
    return {
        "revenue_live": float(row.get("revenue_live") or 0),
        "orders_live": float(row.get("orders_live") or 0),
    }


with st.container(border=True):
    head, refresh = st.columns([5, 1])
    head.markdown("#### Live — near-real-time lane")
    if refresh.button("↻ Refresh", use_container_width=True):
        get_live.clear()
        st.rerun()

    fresh = read_freshness()
    if fresh.no_events_yet:
        st.info(
            "No live events yet. Stream some with **`make stream`** "
            "(or `make stream T=snowflake`), then hit ↻ Refresh."
        )
    else:
        live = get_live()
        l1, l2, l3 = st.columns(3)
        l1.metric("Revenue (live)", eur(live["revenue_live"]))
        l2.metric("Orders (live)", f"{live['orders_live']:,.0f}".replace(",", " "))
        ok = fresh.within_sla(RT_SLA_SECONDS)
        l3.metric(
            f"{'🟢' if ok else '🔴'} Data freshness",
            f"{fresh.freshness_seconds}s ago",
            delta=("within SLA" if ok else f"stale (> {RT_SLA_SECONDS}s)"),
            delta_color="normal" if ok else "inverse",
        )
        st.caption(
            f"Streaming lane · SLA {RT_SLA_SECONDS}s · last event "
            f"{fresh.last_event_ts:%H:%M:%S}. Same `revenue`/`orders` definitions "
            "as the batch KPIs — only fresher."
        )

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
st.subheader("Ask the data — governed agent")
st.caption(
    "The agent maps your question to governed metrics + dimensions and runs "
    "deterministic SQL via MetricFlow. It never invents numbers or SQL."
)

if not settings.anthropic_api_key:
    st.info("Set ANTHROPIC_API_KEY in your .env (or Streamlit secrets) to enable the chat.")
else:
    if "history" not in st.session_state:
        st.session_state.history = []

    # One-click example questions — a recruiter can try the agent without
    # knowing the schema. "Monthly revenue trend" also shows the partial-period
    # warning, since the data ends mid-June.
    examples = [
        "Revenue by product category",
        "Monthly revenue trend",
        "Return rate by country",
        "Average order value by channel",
    ]
    st.caption("Pas d'idée ? Clique sur une question :")
    clicked = None
    for col, q in zip(st.columns(len(examples)), examples, strict=True):
        if col.button(q, use_container_width=True, key=f"ex::{q}"):
            clicked = q

    for item in st.session_state.history:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    prompt = st.chat_input("Pose ta question sur les données retail…") or clicked
    if prompt:
        # Cost control: the public demo spends our Anthropic key, so each
        # visitor IP gets a daily question budget (RATE_LIMIT_PER_DAY).
        # Skipped when no forwarded IP is visible (local dev with your own key).
        forwarded = st.context.headers.get("X-Forwarded-For", "")
        visitor_ip = forwarded.split(",")[0].strip()
        allowed, retry_h = (True, 0)
        if visitor_ip:
            allowed, retry_s = check_rate_limit(visitor_ip, settings.rate_limit_per_day)
            retry_h = max(1, retry_s // 3600)
        if not allowed:
            st.warning(
                f"Limite de démo atteinte : {settings.rate_limit_per_day} questions/jour/IP "
                f"(chaque question déclenche des appels LLM facturés). Réessaie dans "
                f"~{retry_h} h — ou clone le repo et utilise ta propre clé Anthropic "
                "pour un usage illimité.",
                icon="⏳",
            )
        else:
            st.session_state.history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Querying the governed semantic layer…"):
                    res = get_agent().run(prompt)
                render_answer(res)
            st.session_state.history.append({"role": "assistant", "content": res.answer})
