"""Deterministic insights computed in code — not estimated by the LLM.

The semantic layer guarantees the *figures* are correct. The remaining risk is
the model's commentary: "about 40% of revenue", "down from last month", "the
latest month is a decline". So we compute the derivable facts ourselves —
shares of total, period-over-period deltas, rankings, and data coverage — and
hand them to the model to phrase. Code does the arithmetic; the LLM only writes
the sentence. This removes the "~X%" class of hallucination entirely.

`compute()` is pure (rows in, facts out) so it is fully unit-testable without a
warehouse. `coverage()` makes one cached governed query for the latest data date.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from . import semantic_layer as sl
from .catalog import load_catalog
from .guardrails import MetricQuery

_GRAIN_OF = ("day", "week", "month", "quarter", "year")


@dataclass
class Insights:
    """Code-computed facts about one result set (one metric, one grouping)."""

    row_count: int = 0
    metric: str | None = None
    dimension: str | None = None
    is_time_series: bool = False
    total: float | None = None
    # Each entry: {"label": str, "value": float, "share_pct": float}
    shares: list[dict] = field(default_factory=list)
    top: dict | None = None
    bottom: dict | None = None
    # Period-over-period: {"latest", "latest_value", "previous", "previous_value", "abs", "pct"}
    delta: dict | None = None
    partial_latest: bool = False
    coverage: dict = field(default_factory=dict)


def _to_float(x: object) -> float | None:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fmt(v: float) -> str:
    """Human-ish formatting: thousands for big numbers, 2dp for small ones."""
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


@lru_cache(maxsize=1)
def coverage() -> dict:
    """Latest date that has data, via one governed descending-by-day query.

    Cached: the warehouse is static within a run. Best-effort — if the query
    fails (warehouse not built), we return {} and callers degrade gracefully.
    """
    try:
        metric = load_catalog().metric_names[0]
        rows = sl.run_query(
            MetricQuery(
                metrics=[metric],
                group_by=["metric_time__day"],
                order_by=["-metric_time__day"],
                limit=1,
            )
        )
    except Exception:  # noqa: BLE001 — coverage is advisory, never fatal
        return {}
    if not rows:
        return {}
    return {"max_date": str(rows[0].get("metric_time__day", ""))[:10]}


def _parse_date(s: str) -> date | None:
    try:
        y, m, d = (int(p) for p in s[:10].split("-"))
        return date(y, m, d)
    except (ValueError, AttributeError):
        return None


def _end_of_period(start: date, grain: str) -> date:
    """Last calendar day covered by the period that begins at `start`."""
    if grain == "day":
        return start
    if grain == "week":
        return start + timedelta(days=6)
    if grain == "month":
        return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    if grain == "quarter":
        end_month = ((start.month - 1) // 3) * 3 + 3
        return date(start.year, end_month, calendar.monthrange(start.year, end_month)[1])
    if grain == "year":
        return date(start.year, 12, 31)
    return start


def _is_partial(last_label: str, grain: str, max_date: str | None) -> bool:
    """True if the data stops before the latest period is complete."""
    start = _parse_date(last_label)
    maxd = _parse_date(max_date or "")
    if start is None or maxd is None:
        return False
    return maxd < _end_of_period(start, grain)


def compute(rows: list[dict], query: MetricQuery, max_date: str | None = None) -> Insights:
    """Derive deterministic facts from a result set. Pure; safe on empty input."""
    cov = {"max_date": max_date} if max_date else coverage()
    out = Insights(row_count=len(rows), coverage=cov)

    # Shares/deltas only make sense for a single metric.
    if not rows or len(query.metrics) != 1:
        return out
    metric = query.metrics[0]
    out.metric = metric

    # No grouping → a single headline value.
    if not query.group_by:
        v = _to_float(rows[0].get(metric))
        out.total = v
        return out

    time_dim = next((g for g in query.group_by if g.startswith("metric_time")), None)
    cat_dim = next((g for g in query.group_by if not g.startswith("metric_time")), None)
    dim = time_dim or cat_dim
    out.dimension = dim

    raw = [(str(r.get(dim, "")), _to_float(r.get(metric))) for r in rows]
    pairs: list[tuple[str, float]] = [(lbl, v) for lbl, v in raw if v is not None]
    if not pairs:
        return out

    if time_dim and not cat_dim:
        out.is_time_series = True
        grain = time_dim.split("__")[-1] if "__" in time_dim else "day"
        ordered = sorted(pairs, key=lambda kv: kv[0])
        if len(ordered) >= 2:
            (prev_lbl, prev_v), (last_lbl, last_v) = ordered[-2], ordered[-1]
            abs_change = last_v - prev_v
            pct = (abs_change / prev_v * 100) if prev_v else None
            out.delta = {
                "previous": prev_lbl,
                "previous_value": prev_v,
                "latest": last_lbl,
                "latest_value": last_v,
                "abs": abs_change,
                "pct": round(pct, 1) if pct is not None else None,
            }
        out.partial_latest = _is_partial(ordered[-1][0], grain, cov.get("max_date"))
    else:
        total = sum(v for _, v in pairs)
        out.total = total
        if total:
            out.shares = [
                {"label": lbl, "value": v, "share_pct": round(v / total * 100, 1)}
                for lbl, v in pairs
            ]
            ranked = sorted(pairs, key=lambda kv: kv[1])
            out.bottom = {"label": ranked[0][0], "value": ranked[0][1]}
            out.top = {"label": ranked[-1][0], "value": ranked[-1][1]}
    return out


def summarize(ins: Insights) -> str:
    """Render the facts as a compact block to inline in the tool result."""
    if ins.metric is None:
        return ""
    lines = [
        "DETERMINISTIC FACTS (computed in code from the returned rows — cite these "
        "exact numbers, do not estimate):",
        f"- Rows returned: {ins.row_count}.",
    ]
    if ins.coverage.get("max_date"):
        lines.append(f"- Latest date with data: {ins.coverage['max_date']}.")

    if ins.total is not None and not ins.is_time_series:
        lines.append(f"- Total {ins.metric}: {_fmt(ins.total)}.")
    if ins.top and ins.bottom:
        lines.append(
            f"- Highest: {ins.top['label']} ({_fmt(ins.top['value'])}); "
            f"lowest: {ins.bottom['label']} ({_fmt(ins.bottom['value'])})."
        )
    if ins.shares:
        shares = ", ".join(f"{s['label']}={s['share_pct']}%" for s in ins.shares)
        lines.append(f"- Shares of total: {shares}.")
    if ins.delta:
        d = ins.delta
        pct = f" ({d['pct']:+}%)" if d["pct"] is not None else ""
        lines.append(
            f"- {ins.metric} {d['latest']}={_fmt(d['latest_value'])} vs "
            f"{d['previous']}={_fmt(d['previous_value'])}: change {_fmt(d['abs'])}{pct}."
        )
    if ins.partial_latest:
        lines.append(
            "- WARNING: the latest period is PARTIAL (data ends mid-period). Do NOT "
            "describe it as a decline; flag it as incomplete."
        )
    return "\n".join(lines)
