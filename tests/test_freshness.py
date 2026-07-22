"""Unit tests for the streaming freshness reader (against a temp DuckDB)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from governed_analytics_agent.freshness import Freshness, read_freshness


def _make_warehouse(tmp_path: Path, *, empty: bool) -> str:
    """Build a tiny warehouse exposing gold.rt_freshness like the dbt view."""
    db = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create schema if not exists gold")
    if empty:
        con.execute(
            "create view gold.rt_freshness as "
            "select cast(null as timestamp) as last_event_ts, "
            "cast(null as bigint) as freshness_seconds, true as no_events_yet"
        )
    else:
        con.execute(
            "create view gold.rt_freshness as "
            "select timestamp '2026-07-21 16:28:59' as last_event_ts, "
            "cast(42 as bigint) as freshness_seconds, false as no_events_yet"
        )
    con.close()
    return str(db)


def test_read_freshness_with_events(tmp_path: Path) -> None:
    f = read_freshness(_make_warehouse(tmp_path, empty=False))
    assert f.no_events_yet is False
    assert f.freshness_seconds == 42
    assert f.last_event_ts == datetime(2026, 7, 21, 16, 28, 59)


def test_read_freshness_empty_lane(tmp_path: Path) -> None:
    f = read_freshness(_make_warehouse(tmp_path, empty=True))
    assert f.no_events_yet is True
    assert f.freshness_seconds is None


def test_within_sla() -> None:
    assert Freshness(30, None, False).within_sla(120) is True
    assert Freshness(200, None, False).within_sla(120) is False
    # an empty lane has nothing to be stale about
    assert Freshness(None, None, True).within_sla(1) is True
