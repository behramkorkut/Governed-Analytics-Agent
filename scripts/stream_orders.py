"""Stream synthetic order-line events into the ORDER_EVENTS landing table.

Near-real-time lane (Phase 1). Emits `--rate` events/second for `--duration`
seconds (bounded on purpose — cost discipline on the Snowflake free trial), in
~1s micro-batches. In production the same landing table would be fed by Snowpipe
Streaming; here a micro-batch INSERT stands in. Downstream Dynamic Tables /
incremental models refresh Silver/Gold with a small target lag.

Each run CONTINUES the id sequence from the max already in the table, so
order/item ids never collide across runs (event_id is a fresh uuid4 anyway).

Run it as a MODULE (`-m scripts.stream_orders`) so the project root is on
sys.path and the `governed_analytics_agent` package is importable.

Examples
--------
    uv run python -m scripts.stream_orders --target duckdb --rate 5 --duration 20
    uv run python -m scripts.stream_orders --target snowflake --rate 5 --duration 60
    # or simply:  make stream            /  make stream T=snowflake SECS=30
"""

from __future__ import annotations

import argparse
import os
import random
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from governed_analytics_agent.streaming import (
    CREATE_TABLE_DUCKDB,
    CREATE_TABLE_SNOWFLAKE,
    EVENT_COLUMNS,
    ITEM_ID_BASE,
    ITEMS_PER_ORDER,
    OrderEvent,
    load_product_prices,
    make_event,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "data" / "raw" / "products.csv"
_COLS = ", ".join(EVENT_COLUMNS)


def _next_seq_start(max_item_id: int | None) -> int:
    """Continue the global sequence after the last item id, rounded up to a
    clean order boundary so a new run starts a fresh order."""
    if max_item_id is None or max_item_id < ITEM_ID_BASE:
        return 0
    seq = max_item_id - ITEM_ID_BASE + 1
    return ((seq + ITEMS_PER_ORDER - 1) // ITEMS_PER_ORDER) * ITEMS_PER_ORDER


def _generate(
    prices: dict[int, float], seq_start: int, rate: int, duration: int, seed: int
) -> Iterator[list[OrderEvent]]:
    """Yield one ~1-second micro-batch of `rate` events, `duration` times,
    continuing the global sequence from `seq_start`."""
    rng = random.Random(seed)
    seq = seq_start
    for _ in range(duration):
        start = time.monotonic()
        now = datetime.now(UTC)
        batch = [make_event(rng, prices, seq + i, now=now) for i in range(rate)]
        seq += rate
        yield batch
        time.sleep(max(0.0, 1.0 - (time.monotonic() - start)))


def _emit(batch: list[OrderEvent], total: int) -> int:
    total += len(batch)
    print(f"  +{len(batch):>3} events  (total {total})", flush=True)
    return total


def write_duckdb(rate: int, duration: int, seed: int) -> int:
    import duckdb

    db_path = os.environ.get("WAREHOUSE_DB", str(PROJECT_ROOT / "data" / "warehouse.duckdb"))
    con = duckdb.connect(db_path)
    total = 0
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        con.execute(CREATE_TABLE_DUCKDB)
        max_item = con.execute("SELECT max(order_item_id) FROM bronze.order_events").fetchone()[0]
        prices = load_product_prices(PRODUCTS_CSV)
        placeholders = ", ".join(["?"] * len(EVENT_COLUMNS))
        sql = f"INSERT INTO bronze.order_events ({_COLS}) VALUES ({placeholders})"
        for batch in _generate(prices, _next_seq_start(max_item), rate, duration, seed):
            con.executemany(sql, [e.as_row() for e in batch])
            total = _emit(batch, total)
    finally:
        con.close()
    return total


def write_snowflake(rate: int, duration: int, seed: int) -> int:
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
        max_item = cur.execute("SELECT max(ORDER_ITEM_ID) FROM BRONZE.ORDER_EVENTS").fetchone()[0]
        prices = load_product_prices(PRODUCTS_CSV)
        placeholders = ", ".join(["%s"] * len(EVENT_COLUMNS))
        sql = f"INSERT INTO BRONZE.ORDER_EVENTS ({_COLS}) VALUES ({placeholders})"
        for batch in _generate(prices, _next_seq_start(max_item), rate, duration, seed):
            cur.executemany(sql, [e.as_row() for e in batch])
            total = _emit(batch, total)
        cur.close()
    finally:
        con.close()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream synthetic order events.")
    parser.add_argument("--target", choices=["duckdb", "snowflake"], default="duckdb")
    parser.add_argument("--rate", type=int, default=5, help="events per second")
    parser.add_argument("--duration", type=int, default=20, help="seconds to stream")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Streaming ~{args.rate} events/s for {args.duration}s into {args.target} (ORDER_EVENTS)")
    writer = write_snowflake if args.target == "snowflake" else write_duckdb
    total = writer(args.rate, args.duration, args.seed)
    print(f"Done. {total} events streamed into ORDER_EVENTS ({args.target}).")


if __name__ == "__main__":
    main()
