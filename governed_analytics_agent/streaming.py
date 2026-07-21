"""Synthetic order-event generation for the near-real-time (streaming) lane.

The batch pipeline (orders + order_items CSVs) has day-grain dates. The streaming
lane emits **timestamped** order-line events into a landing table `ORDER_EVENTS`,
which in production would be fed by Snowpipe Streaming and here is fed by a
micro-batch INSERT (scripts/stream_orders.py). Downstream, Dynamic Tables
(Snowflake) / incremental models (DuckDB) refresh Silver/Gold with a small target
lag — that's Phase 2. This module holds the pure, testable event generation; the
I/O runner lives in scripts/ so this stays deterministic and unit-tested.
"""

from __future__ import annotations

import csv
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CHANNELS = ["online", "in_store"]
# Streaming traffic is mostly completed orders, with a realistic tail of
# returns/cancellations (kept in sync with the batch status enum).
STATUS_WEIGHTS: list[tuple[str, float]] = [
    ("completed", 0.85),
    ("returned", 0.08),
    ("cancelled", 0.07),
]

# Streaming ids start well above the batch range (~2.2k orders / ~5.5k items) so
# live events can never collide with the historical CSV load.
ORDER_ID_BASE = 1_000_000
ITEM_ID_BASE = 5_000_000
ITEMS_PER_ORDER = 3

# Column order used by both the DDL and the INSERT in scripts/stream_orders.py.
EVENT_COLUMNS = [
    "event_id",
    "order_id",
    "order_item_id",
    "customer_id",
    "store_id",
    "product_id",
    "quantity",
    "unit_price",
    "channel",
    "status",
    "event_ts",
]

# Landing-table DDL. event_ts is a real timestamp (streaming sources carry one),
# unlike the day-grain batch — that's what enables "last N minutes" windows.
CREATE_TABLE_DUCKDB = """
CREATE TABLE IF NOT EXISTS bronze.order_events (
    event_id      VARCHAR,
    order_id      BIGINT,
    order_item_id BIGINT,
    customer_id   BIGINT,
    store_id      BIGINT,
    product_id    BIGINT,
    quantity      INTEGER,
    unit_price    DECIMAL(10, 2),
    channel       VARCHAR,
    status        VARCHAR,
    event_ts      TIMESTAMP
)
"""

CREATE_TABLE_SNOWFLAKE = """
CREATE TABLE IF NOT EXISTS BRONZE.ORDER_EVENTS (
    EVENT_ID      VARCHAR,
    ORDER_ID      NUMBER,
    ORDER_ITEM_ID NUMBER,
    CUSTOMER_ID   NUMBER,
    STORE_ID      NUMBER,
    PRODUCT_ID    NUMBER,
    QUANTITY      NUMBER,
    UNIT_PRICE    NUMBER(10, 2),
    CHANNEL       VARCHAR,
    STATUS        VARCHAR,
    EVENT_TS      TIMESTAMP_NTZ
)
"""


@dataclass(frozen=True)
class OrderEvent:
    """One streamed order line (the grain of the near-real-time fact)."""

    event_id: str
    order_id: int
    order_item_id: int
    customer_id: int
    store_id: int
    product_id: int
    quantity: int
    unit_price: float
    channel: str
    status: str
    event_ts: datetime

    def as_row(self) -> tuple[object, ...]:
        """Positional tuple in EVENT_COLUMNS order (for parameterized INSERT)."""
        return (
            self.event_id,
            self.order_id,
            self.order_item_id,
            self.customer_id,
            self.store_id,
            self.product_id,
            self.quantity,
            self.unit_price,
            self.channel,
            self.status,
            self.event_ts,
        )


def load_product_prices(products_csv: Path) -> dict[int, float]:
    """Read {product_id: list_price} from the generated products landing file so
    streamed prices are consistent with the existing product dimension."""
    prices: dict[int, float] = {}
    with products_csv.open(newline="") as f:
        for row in csv.DictReader(f):
            prices[int(row["product_id"])] = float(row["list_price"])
    if not prices:
        raise ValueError(f"No products found in {products_csv}")
    return prices


def _weighted_status(rng: random.Random) -> str:
    r = rng.random()
    cumulative = 0.0
    for status, weight in STATUS_WEIGHTS:
        cumulative += weight
        if r <= cumulative:
            return status
    return STATUS_WEIGHTS[-1][0]


def make_event(
    rng: random.Random,
    prices: dict[int, float],
    seq: int,
    *,
    now: datetime | None = None,
) -> OrderEvent:
    """Build one plausible order-line event.

    `rng` is a seeded Random for reproducibility; `seq` is a monotonic counter
    that drives the order/item ids (so ~ITEMS_PER_ORDER lines share an order).
    """
    event_ts = now if now is not None else datetime.now(UTC)
    product_id = rng.choice(list(prices))
    list_price = prices[product_id]
    discount = rng.choice([0.0, 0.05, 0.10, 0.15, 0.20])
    unit_price = round(list_price * (1 - discount), 2)
    return OrderEvent(
        event_id=str(uuid.UUID(int=rng.getrandbits(128))),
        order_id=ORDER_ID_BASE + seq // ITEMS_PER_ORDER,
        order_item_id=ITEM_ID_BASE + seq,
        customer_id=rng.randint(1, 500),
        store_id=rng.randint(1, 10),
        product_id=product_id,
        quantity=rng.randint(1, 5),
        unit_price=unit_price,
        channel=rng.choice(CHANNELS),
        status=_weighted_status(rng),
        event_ts=event_ts,
    )
