# Deploying on Snowflake

DuckDB is the default so anyone can clone the repo and run the whole stack in
one command, at zero cost. Because **dbt and MetricFlow are warehouse-agnostic**,
moving to Snowflake (e.g. on trial credits) changes the *connection*, not the
analytics logic: the Silver/Gold models, the semantic models, the 12 metrics and
the governed agent are reused as-is.

## What actually changes

1. **The dbt profile.** Swap the DuckDB adapter for Snowflake in
   `dbt/retail_dwh/profiles.yml`:

   ```yaml
   retail_dwh:
     target: snowflake
     outputs:
       snowflake:
         type: snowflake
         account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
         user: "{{ env_var('SNOWFLAKE_USER') }}"
         authenticator: externalbrowser        # or key-pair auth (recommended for CI)
         role: "{{ env_var('SNOWFLAKE_ROLE', 'SYSADMIN') }}"
         warehouse: "{{ env_var('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH') }}"
         database: "{{ env_var('SNOWFLAKE_DATABASE', 'RETAIL_DWH') }}"
         schema: bronze
         threads: 4
   ```

   Install the adapter: `uv add dbt-snowflake`.

2. **Loading the Bronze layer.** Instead of DuckDB reading local CSVs, land the
   files in a stage and `COPY INTO` Snowflake tables (or use the Python
   connector). Sketch:

   ```sql
   CREATE SCHEMA IF NOT EXISTS bronze;
   CREATE STAGE IF NOT EXISTS bronze.landing;
   -- PUT file://data/raw/customers.csv @bronze.landing;   (via snowsql)
   COPY INTO bronze.customers
     FROM @bronze.landing/customers.csv
     FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');
   ```

3. **Credentials** go in `.env` (never committed): `SNOWFLAKE_ACCOUNT`,
   `SNOWFLAKE_USER`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_ROLE`.

That's it — `dbt build`, `dbt parse`, `mf query` and the agent all work the same,
because MetricFlow has a native Snowflake engine.

## Dialect notes (the honest caveats)

A few models use DuckDB-specific SQL and need a Snowflake equivalent:

- **`dim_dates`** uses DuckDB's `range(DATE, DATE, INTERVAL)` and `strftime`.
  On Snowflake, generate the spine with `GENERATOR` + `DATEADD`, and format with
  `TO_CHAR` (e.g. `TO_CHAR(date_day, 'YYYYMMDD')`, `DAYNAME`, `MONTHNAME`).
- Casts like `cast(... as decimal(10,2))` are portable; `strftime` in
  `fact_sales.date_id` becomes `TO_CHAR(order_date, 'YYYYMMDD')::int`.

Keeping these warehouse-specific bits isolated in the date dimension (and using
a dbt macro per adapter) is the clean way to stay portable.

## Cost

A Snowflake trial gives free credits; an `X-SMALL` warehouse with auto-suspend
is plenty for this dataset. Suspend the warehouse when idle to preserve credits.
```
