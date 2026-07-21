"""Unit tests for the streaming event generator (pure, no I/O)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from governed_analytics_agent.streaming import (
    CHANNELS,
    EVENT_COLUMNS,
    ITEM_ID_BASE,
    ORDER_ID_BASE,
    STATUS_WEIGHTS,
    make_event,
)

PRICES = {1: 100.0, 2: 50.0, 3: 400.0}
_VALID_STATUS = {s for s, _ in STATUS_WEIGHTS}
_NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


def test_make_event_is_deterministic_for_a_given_seed() -> None:
    e1 = make_event(random.Random(42), PRICES, 0, now=_NOW)
    e2 = make_event(random.Random(42), PRICES, 0, now=_NOW)
    assert e1 == e2


def test_make_event_fields_are_valid() -> None:
    e = make_event(random.Random(7), PRICES, 5, now=_NOW)
    assert e.product_id in PRICES
    assert 1 <= e.customer_id <= 500
    assert 1 <= e.store_id <= 10
    assert 1 <= e.quantity <= 5
    assert e.unit_price <= PRICES[e.product_id]  # discount never raises the price
    assert e.channel in CHANNELS
    assert e.status in _VALID_STATUS
    assert e.event_ts == _NOW


def test_ids_avoid_the_batch_range_and_group_by_order() -> None:
    # seq 0,1,2 share one order; seq 3 starts the next — never colliding with batch ids.
    orders = [make_event(random.Random(1), PRICES, seq, now=_NOW).order_id for seq in range(4)]
    assert orders[0] == orders[1] == orders[2] == ORDER_ID_BASE
    assert orders[3] == ORDER_ID_BASE + 1
    assert make_event(random.Random(1), PRICES, 0, now=_NOW).order_item_id == ITEM_ID_BASE


def test_as_row_matches_column_order() -> None:
    e = make_event(random.Random(3), PRICES, 0, now=_NOW)
    row = e.as_row()
    assert len(row) == len(EVENT_COLUMNS)
    assert row[0] == e.event_id
    assert row[-1] == e.event_ts
