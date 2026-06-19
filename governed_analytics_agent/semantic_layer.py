"""Thin client over the MetricFlow CLI (`mf`).

We shell out to `mf query` with validated arguments. MetricFlow compiles the
metric/dimension selection into deterministic SQL and runs it against DuckDB.
The agent therefore NEVER emits SQL itself — it only chooses metrics+dimensions.
"""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from .catalog import load_catalog
from .config import settings
from .guardrails import Filter, MetricQuery


class SemanticLayerError(RuntimeError):
    pass


def _quote(v: object) -> str:
    """Quote a scalar value, escaping single quotes (defence vs injection)."""
    return "'" + str(v).replace("'", "''") + "'"


def _compile_condition(f: Filter, time_dimensions: set[str]) -> str:
    """Compile one structured filter into a MetricFlow where-expression.

    Categorical -> {{ Dimension('dim') }} op value
    Time        -> {{ TimeDimension('dim', 'grain') }} op value
    No raw SQL is ever taken from the model: only validated names/operators.
    """
    if f.dimension in time_dimensions:
        ref = f"{{{{ TimeDimension('{f.dimension}', '{f.grain or 'day'}') }}}}"
    else:
        ref = f"{{{{ Dimension('{f.dimension}') }}}}"

    if f.operator == "in":
        values = f.value if isinstance(f.value, list) else [f.value]
        rendered = "(" + ", ".join(_quote(v) for v in values) + ")"
        return f"{ref} IN {rendered}"
    return f"{ref} {f.operator} {_quote(f.value)}"


def compile_where(query: MetricQuery, time_dimensions: set[str]) -> str | None:
    if not query.filters:
        return None
    return " AND ".join(_compile_condition(f, time_dimensions) for f in query.filters)


def _base_cmd() -> list[str]:
    # `uv run mf ...` so it works with the project's locked environment.
    return ["uv", "run", "mf"]


def _run_mf(args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **settings.metricflow_env(), **(extra_env or {})}
    return subprocess.run(
        _base_cmd() + args,
        cwd=str(settings.dbt_project_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@lru_cache(maxsize=1)
def _time_dimensions() -> frozenset[str]:
    return frozenset(load_catalog().time_dimensions)


def _query_args(q: MetricQuery) -> list[str]:
    args = ["query", "--metrics", ",".join(q.metrics)]
    if q.group_by:
        args += ["--group-by", ",".join(q.group_by)]
    where = compile_where(q, set(_time_dimensions()))
    if where:
        args += ["--where", where]
    if q.order_by:
        args += ["--order", ",".join(q.order_by)]
    if q.limit:
        args += ["--limit", str(q.limit)]
    return args


def run_query(q: MetricQuery) -> list[dict]:
    """Execute the metric query and return rows as a list of dicts."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.csv"
        proc = _run_mf(_query_args(q) + ["--csv", str(out)])
        if proc.returncode != 0 or not out.exists():
            raise SemanticLayerError(
                f"MetricFlow query failed:\n{proc.stderr or proc.stdout}"
            )
        with out.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def explain_sql(q: MetricQuery) -> str:
    """Return the deterministic SQL MetricFlow would run (for transparency)."""
    proc = _run_mf(_query_args(q) + ["--explain"])
    text = proc.stdout
    marker = "SELECT"
    idx = text.find(marker)
    return text[idx:].strip() if idx != -1 else text.strip()
