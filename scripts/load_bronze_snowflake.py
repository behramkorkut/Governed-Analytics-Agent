"""Load the raw CSV landing zone into Snowflake, schema `BRONZE`.

Snowflake counterpart of scripts/load_bronze.py (which targets DuckDB). Same
contract: Bronze is raw ingestion — no cleaning or dedup; typing/conforming is
the job of the Silver (staging) dbt models.

We load via pandas + snowflake `write_pandas` (auto-creates the tables). Column
names are UPPERCASED and written UNQUOTED so they become standard Snowflake
identifiers (CUSTOMER_ID, not "customer_id") — this is what lets the dbt models
reference `customer_id` unquoted and stay identical across DuckDB and Snowflake.
Like the DuckDB loader, the two date columns are kept as text so that casting
stays a visible, explicit Silver-layer job.

Prereqs:  uv sync --extra snowflake   and the SNOWFLAKE_* env vars (.env.example).
Run:      set -a && source .env && set +a   # export the vars into the shell
          uv run python scripts/load_bronze_snowflake.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
TABLES = ["customers", "products", "stores", "orders", "order_items"]

# Columns kept as raw text in Bronze (mirrors scripts/load_bronze.py): casting to
# a real date is an explicit Silver-layer step, not a Bronze concern.
RAW_AS_TEXT = {
    "customers": ["signup_date"],
    "orders": ["order_date"],
}


def main() -> None:
    try:
        from snowflake.connector import connect
        from snowflake.connector.pandas_tools import write_pandas
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "snowflake-connector-python[pandas] is not installed. Run: uv sync --extra snowflake"
        ) from exc

    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)} (see .env.example)")

    database = os.environ.get("SNOWFLAKE_DATABASE", "RETAIL_DWH")
    con = connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=database,
    )
    try:
        cur = con.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        cur.execute(f"USE DATABASE {database}")
        cur.execute("CREATE SCHEMA IF NOT EXISTS BRONZE")
        cur.close()

        print(f"Loading Bronze into {database}.BRONZE (Snowflake)")
        for name in TABLES:
            csv_path = RAW_DIR / f"{name}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(
                    f"Missing landing file: {csv_path} (run generate_raw_data.py first)"
                )
            dtype = dict.fromkeys(RAW_AS_TEXT.get(name, []), str)
            df = pd.read_csv(csv_path, dtype=dtype)
            # UPPERCASE, unquoted -> standard Snowflake identifiers.
            df.columns = [c.upper() for c in df.columns]
            _success, _nchunks, nrows, _ = write_pandas(
                con,
                df,
                table_name=name.upper(),
                database=database,
                schema="BRONZE",
                auto_create_table=True,
                overwrite=True,
                quote_identifiers=False,
            )
            print(f"  BRONZE.{name:<12} {nrows:>6} rows")
    finally:
        con.close()
    print("Bronze layer ready (Snowflake).")


if __name__ == "__main__":
    main()
