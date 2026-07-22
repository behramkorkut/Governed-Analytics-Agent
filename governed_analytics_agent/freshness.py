"""Read the freshness of the near-real-time lane (streaming).

Freshness is *not* a MetricFlow metric on purpose: it is non-additive, evaluated
at query time, and derived from `current_timestamp` (non-deterministic). It is an
operational/health signal, so it lives in a dedicated `rt_freshness` view and is
read directly here — the business metrics stay in the governed semantic layer.

This reader targets the local DuckDB warehouse (the offline demo + dashboard).
The Snowflake demo reads the same view through its own connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb

from .config import settings

_QUERY = "select freshness_seconds, last_event_ts, no_events_yet from gold.rt_freshness"


@dataclass(frozen=True)
class Freshness:
    """How fresh the streaming lane is, as of the moment it was read."""

    freshness_seconds: int | None
    last_event_ts: datetime | None
    no_events_yet: bool

    def within_sla(self, sla_seconds: int) -> bool:
        """True if the lane has events and they are fresher than the SLA.

        An empty lane (no events yet) is treated as within SLA — there is simply
        nothing to be stale about.
        """
        if self.no_events_yet or self.freshness_seconds is None:
            return True
        return self.freshness_seconds <= sla_seconds


def read_freshness(db_path: str | None = None) -> Freshness:
    """Read the single `gold.rt_freshness` row from the DuckDB warehouse."""
    path = db_path or str(settings.warehouse_db_abs)
    con = duckdb.connect(path, read_only=True)
    try:
        row = con.execute(_QUERY).fetchone()
    finally:
        con.close()
    if row is None:
        return Freshness(freshness_seconds=None, last_event_ts=None, no_events_yet=True)
    freshness_seconds, last_event_ts, no_events_yet = row
    return Freshness(
        freshness_seconds=int(freshness_seconds) if freshness_seconds is not None else None,
        last_event_ts=last_event_ts,
        no_events_yet=bool(no_events_yet),
    )
