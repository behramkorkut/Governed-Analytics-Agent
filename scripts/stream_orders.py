"""Stream synthetic order-line events into the ORDER_EVENTS landing table.

Near-real-time lane (Phase 1). Emits `--rate` events/second for `--duration`
seconds (bounded on purpose — cost discipline on the Snowflake free trial), in
~1s micro-batches. In production the same landing table would be fed by Snowpipe
Streaming; here a micro-batch INSERT stands in. Downstream Dynamic Tables /
incremental models (Phase 2) refresh Silver/Gold with a small target lag.

Examples
--------
    # local DuckDB warehouse (offline, CI-safe)
    uv run python scripts/stream_orders.py --target duckdb --rate 5 --duration 20

    # Snowflake (needs: set -a && source .env && set +a ; uv sync --extra snowflake)
    uv run python scripts/stream_orders.py --target snowflake --rate 5 --duration 60
"""

from __future__ import annotations

import argparse
import os
import random
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from governed_analytics_agent.streaming import (
    CREATE_TABLE_DUCKDB,
    CREATE_TABLE_SNOWFLAKE,
    EVENT_COLUMNS,
    OrderEvent,
    load_product_prices,
    make_event,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "data" / "raw" / "products.csv"
_COLS = ", ".join(EVENT_COLUMNS)


def _rows(events: Iterable[OrderEvent]) -> list[tuple[object, ...]]:
    return [e.as_row() for e in events]


def write_duckdb(batches: Iterable[list[OrderEvent]]) -> int:
    import duckdb

    db_path = os.environ.get("WAREHOUSE_DB", str(PROJECT_ROOT / "data" / "warehouse.duckdb"))
    con = duckdb.connect(db_path)
    total = 0
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        con.execute(CREATE_TABLE_DUCKDB)
        placeholders = ", ".join(["?"] * len(EVENT_COLUMNS))
        sql = f"INSERT INTO bronze.order_events ({_COLS}) VALUES ({placeholders})"
        for batch in batches:
            con.executemany(sql, _rows(batch))
            total += len(batch)
            print(f"  +{len(batch):>3} events  (total {total})", flush=True)
    finally:
        con.close()
    return total


def write_snowflake(batches: Iterable[list[OrderEvent]]) -> int:
    from snowflake.connector import connect

    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)} (see .env.example)")

    con = connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "RETAIL_DWH"),
    )
    total = 0
    try:
        cur = con.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS BRONZE")
        cur.execute(CREATE_TABLE_SNOWFLAKE)
        placeholders = ", ".join(["%s"] * len(EVENT_COLUMNS))
        sql = f"INSERT INTO BRONZE.ORDER_EVENTS ({_COLS}) VALUES ({placeholders})"
        for batch in batches:
            cur.executemany(sql, _rows(batch))
            total += len(batch)
            print(f"  +{len(batch):>3} events  (total {total})", flush=True)
        cur.close()
    finally:
        con.close()
    return total


def _stream_batches(
    rate: int, duration: int, seed: int
) -> Iterable[list[OrderEvent]]:
    """Yield one ~1-second micro-batch of `rate` events, `duration` times."""
    rng = random.Random(seed)
    prices = load_product_prices(PRODUCTS_CSV)
    seq = 0
    for _ in range(duration):
        start = time.monotonic()
        now = datetime.now(UTC)
        batch = [make_event(rng, prices, seq + i, now=now) for i in range(rate)]
        seq += rate
        yield batch
        # keep a ~1s cadence between micro-batches
        elapsed = time.monotonic() - start
        time.sleep(max(0.0, 1.0 - elapsed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream synthetic order events.")
    parser.add_argument("--target", choices=["duckdb", "snowflake"], default="duckdb")
    parser.add_argument("--rate", type=int, default=5, help="events per second")
    parser.add_argument("--duration", type=int, default=20, help="seconds to stream")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(
        f"Streaming ~{args.rate} events/s for {args.duration}s "
        f"into {args.target} (ORDER_EVENTS)"
    )
    batches = _stream_batches(args.rate, args.duration, args.seed)
    writer = write_snowflake if args.target == "snowflake" else write_duckdb
    total = writer(batches)
    print(f"Done. {total} events streamed into ORDER_EVENTS ({args.target}).")


if __name__ == "__main__":
    main()
