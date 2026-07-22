"""Load the raw CSV landing zone into DuckDB, schema `bronze`.

Bronze = raw, untouched ingestion. We deliberately do NOT clean, cast or
deduplicate here. We just land the source files into the warehouse so that
everything downstream (Silver/Gold in dbt) is rebuildable from this layer
without re-reading the source systems.

DuckDB note: `read_csv_auto` infers the schema. We force the two date
columns to VARCHAR on purpose, so that *type casting* becomes an explicit,
visible job of the Silver layer (a classic interview talking point:
"where do you cast and conform types?" -> in Silver, never in Bronze).

It also provisions the (empty) streaming landing table `bronze.order_events`, so
the near-real-time models build on a fresh clone or in CI, before any event has
been produced. The DDL is owned by the package — single source of truth.

Run it as a MODULE (`-m scripts.load_bronze`) so the project root is on sys.path
and the `governed_analytics_agent` package is importable — the project is not
pip-installed.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from governed_analytics_agent.streaming import CREATE_TABLE_DUCKDB

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# 12-factor config: the warehouse path is read from the environment, with a
# sensible default inside the project. Override with WAREHOUSE_DB=/some/path.
DB_PATH = Path(os.environ.get("WAREHOUSE_DB", PROJECT_ROOT / "data" / "warehouse.duckdb"))

# table -> columns we want to keep as raw text (VARCHAR) instead of inferred
RAW_AS_TEXT = {
    "customers": ["signup_date"],
    "orders": ["order_date"],
}


def load_table(con: duckdb.DuckDBPyConnection, name: str) -> int:
    csv_path = RAW_DIR / f"{name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Missing landing file: {csv_path} (run generate_raw_data.py first)"
        )

    # Build an optional types override (force some columns to VARCHAR)
    overrides = RAW_AS_TEXT.get(name)
    types_clause = ""
    if overrides:
        mapping = ", ".join(f"'{c}': 'VARCHAR'" for c in overrides)
        types_clause = f", types = {{{mapping}}}"

    con.execute(f"DROP TABLE IF EXISTS bronze.{name};")
    con.execute(
        f"CREATE TABLE bronze.{name} AS "
        f"SELECT * FROM read_csv_auto('{csv_path.as_posix()}', header = true{types_clause});"
    )
    return con.execute(f"SELECT count(*) FROM bronze.{name};").fetchone()[0]


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze;")

    print(f"Loading Bronze into {DB_PATH}")
    for table in ["customers", "products", "stores", "orders", "order_items"]:
        n = load_table(con, table)
        print(f"  bronze.{table:<12} {n:>6} rows")

    # Streaming landing table: created empty if absent, never truncated (live
    # events accumulate across runs). Guarantees the near-real-time models can
    # build even when no event has been streamed yet.
    con.execute(CREATE_TABLE_DUCKDB)
    n_events = con.execute("SELECT count(*) FROM bronze.order_events").fetchone()[0]
    print(f"  bronze.order_events {n_events:>5} rows (streaming landing)")

    con.close()
    print("Bronze layer ready.")


if __name__ == "__main__":
    main()
