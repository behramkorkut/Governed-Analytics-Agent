"""Generate synthetic retail source data (the "landing zone").

This simulates raw extracts coming from operational source systems
(an e-commerce backend + a store POS). Output = CSV files in data/raw/.

Design choices worth defending in an interview:
- Deterministic seeds (random + Faker) => the dataset is reproducible.
  Anyone who clones the repo gets the exact same numbers.
- Normalized, OLTP-style sources (orders + order_items separately),
  NOT a pre-joined flat table. The star schema is built later, in dbt.
- Intentional "messiness" (inconsistent country casing, mixed-case
  emails, stray whitespace, a few NULLs). Bronze keeps it as-is; the
  Silver dbt layer is what cleans/conforms it. That is the whole point
  of the Medallion pattern.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# --- Reproducibility -------------------------------------------------------
SEED = 42
random.seed(SEED)
fake = Faker("fr_FR")
Faker.seed(SEED)

# --- Volumes (aligned with the modern-dwh-dbt-airflow star schema) ---------
N_CUSTOMERS = 500
N_PRODUCTS = 100
N_STORES = 10
N_ORDERS = 2200

START_DATE = date(2024, 1, 1)
END_DATE = date(2026, 6, 15)

# --- Reference data --------------------------------------------------------
# Canonical country -> messy variants we will randomly inject, so Silver has
# real work to do (standardizing them back to the canonical form).
COUNTRY_VARIANTS = {
    "France": ["France", "france", "FR", " France ", "FRA"],
    "Germany": ["Germany", "germany", "DE", "Deutschland"],
    "Spain": ["Spain", "spain", "ES", "España"],
    "Italy": ["Italy", "italy", "IT", "Italia"],
    "Belgium": ["Belgium", "belgium", "BE", " Belgique"],
}
COUNTRIES = list(COUNTRY_VARIANTS)

CATEGORIES = {
    "Electronics": (40.0, 900.0, 0.35),  # (min cost, max cost, target margin)
    "Clothing": (5.0, 120.0, 0.55),
    "Home": (8.0, 300.0, 0.45),
    "Sports": (10.0, 400.0, 0.40),
}

CHANNELS = (["online"] * 6) + (["in_store"] * 4)  # ~60% online
STATUSES = (["completed"] * 82) + (["returned"] * 10) + (["cancelled"] * 8)

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def messy_country() -> str:
    """Pick a country then return one of its inconsistent spellings."""
    canonical = random.choice(COUNTRIES)
    return random.choice(COUNTRY_VARIANTS[canonical])


def random_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    path = RAW_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  wrote {path.relative_to(RAW_DIR.parents[1])}  ({len(rows)} rows)")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating synthetic retail data into {RAW_DIR} (seed={SEED})")

    # 1) CUSTOMERS ----------------------------------------------------------
    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        first = fake.first_name()
        last = fake.last_name()
        # mixed-case email + occasional stray whitespace on the name
        email = (
            f"{first}.{last}@{fake.free_email_domain()}".upper()
            if cid % 7 == 0
            else f"{first.lower()}.{last.lower()}@{fake.free_email_domain()}"
        )
        name_display = f" {first}" if cid % 11 == 0 else first  # leading space sometimes
        city = None if cid % 23 == 0 else fake.city()  # a few NULL cities
        customers.append(
            [
                cid,
                name_display,
                last,
                email,
                messy_country(),
                city,
                random_date(START_DATE, END_DATE).isoformat(),
            ]
        )
    write_csv(
        "customers",
        ["customer_id", "first_name", "last_name", "email", "country", "city", "signup_date"],
        customers,
    )

    # 2) PRODUCTS -----------------------------------------------------------
    products = []
    for pid in range(1, N_PRODUCTS + 1):
        category = random.choice(list(CATEGORIES))
        cmin, cmax, margin = CATEGORIES[category]
        unit_cost = round(random.uniform(cmin, cmax), 2)
        list_price = round(unit_cost * (1 + margin + random.uniform(-0.05, 0.10)), 2)
        products.append(
            [
                pid,
                f"{category[:3].upper()}-{fake.word().capitalize()}-{pid:03d}",
                category,
                unit_cost,
                list_price,
            ]
        )
    write_csv(
        "products",
        ["product_id", "product_name", "category", "unit_cost", "list_price"],
        products,
    )

    # 3) STORES -------------------------------------------------------------
    stores = []
    for sid in range(1, N_STORES + 1):
        country = COUNTRIES[(sid - 1) % len(COUNTRIES)]
        stores.append([sid, f"Store {fake.city()}", country, fake.city()])
    write_csv("stores", ["store_id", "store_name", "country", "city"], stores)

    # 4) ORDERS + 5) ORDER_ITEMS -------------------------------------------
    orders = []
    order_items = []
    item_id = 0
    for oid in range(1, N_ORDERS + 1):
        customer_id = random.randint(1, N_CUSTOMERS)
        store_id = random.randint(1, N_STORES)
        order_date = random_date(START_DATE, END_DATE)
        channel = random.choice(CHANNELS)
        status = random.choice(STATUSES)
        orders.append([oid, customer_id, store_id, order_date.isoformat(), channel, status])

        # 1..4 distinct products per order
        for product_id in random.sample(range(1, N_PRODUCTS + 1), random.randint(1, 4)):
            item_id += 1
            quantity = random.randint(1, 5)
            list_price = products[product_id - 1][4]
            # occasional discount on the line (0%, 10% or 15%)
            discount = random.choice([0.0, 0.0, 0.0, 0.10, 0.15])
            unit_price = round(list_price * (1 - discount), 2)
            order_items.append([item_id, oid, product_id, quantity, unit_price])

    write_csv(
        "orders",
        ["order_id", "customer_id", "store_id", "order_date", "channel", "status"],
        orders,
    )
    write_csv(
        "order_items",
        ["order_item_id", "order_id", "product_id", "quantity", "unit_price"],
        order_items,
    )

    print(f"Done. {len(orders)} orders, {len(order_items)} order lines.")


if __name__ == "__main__":
    main()
