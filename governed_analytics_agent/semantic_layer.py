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
from pathlib import Path

from .config import settings
from .guardrails import MetricQuery


class SemanticLayerError(RuntimeError):
    pass


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


def _query_args(q: MetricQuery) -> list[str]:
    args = ["query", "--metrics", ",".join(q.metrics)]
    if q.group_by:
        args += ["--group-by", ",".join(q.group_by)]
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
