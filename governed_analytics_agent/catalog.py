"""Metric & dimension catalog, loaded from the dbt/MetricFlow semantic manifest.

This is the allow-list the agent is constrained to. Metrics and dimensions are
read from target/semantic_manifest.json (produced by `dbt parse`), so the
catalog is ALWAYS in sync with the codified semantic layer — there is no second
place to maintain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    description: str


@dataclass
class Catalog:
    metrics: dict[str, Metric] = field(default_factory=dict)
    dimensions: list[str] = field(default_factory=list)
    time_dimensions: set[str] = field(default_factory=set)

    @property
    def metric_names(self) -> list[str]:
        return sorted(self.metrics)

    def describe(self) -> str:
        """A compact catalog description to inline in the system prompt."""
        lines = ["METRICS:"]
        for m in sorted(self.metrics.values(), key=lambda x: x.name):
            lines.append(f"  - {m.name}: {m.description or m.label}")
        lines.append("DIMENSIONS (use to group/slice):")
        for d in self.dimensions:
            lines.append(f"  - {d}")
        lines.append(
            "TIME: use 'metric_time' for time series; add a grain like "
            "metric_time__month / __quarter / __year."
        )
        return "\n".join(lines)


def _primary_entity(semantic_model: dict) -> str | None:
    for e in semantic_model.get("entities", []):
        if e.get("type") == "primary":
            return e["name"]
    return None


def load_catalog(manifest_path: Path | None = None) -> Catalog:
    path = Path(manifest_path or settings.semantic_manifest_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Semantic manifest not found at {path}.\n"
            f"Run:  (cd {settings.dbt_project_dir} && DBT_PROFILES_DIR=$PWD uv run dbt parse)"
        )

    manifest = json.loads(path.read_text())

    metrics: dict[str, Metric] = {}
    for m in manifest.get("metrics", []):
        name = m["name"]
        metrics[name] = Metric(
            name=name,
            label=m.get("label") or name,
            description=(m.get("description") or "").strip(),
        )

    # Build qualified dimension names exactly like MetricFlow does:
    #   <primary_entity>__<dimension>  (+ the special metric_time)
    dims: set[str] = {"metric_time"}
    time_dims: set[str] = {"metric_time"}
    for sm in manifest.get("semantic_models", []):
        prefix = _primary_entity(sm)
        if not prefix:
            continue
        for d in sm.get("dimensions", []):
            qualified = f"{prefix}__{d['name']}"
            dims.add(qualified)
            if d.get("type") == "time":
                time_dims.add(qualified)

    return Catalog(metrics=metrics, dimensions=sorted(dims), time_dimensions=time_dims)
