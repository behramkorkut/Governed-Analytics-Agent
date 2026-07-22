{%- set is_snowflake = target.type == 'snowflake' -%}
{{
    config(
        materialized = 'dynamic_table' if is_snowflake else 'incremental',
        target_lag = '1 minute' if is_snowflake else none,
        snowflake_warehouse = target.warehouse if is_snowflake else none,
        unique_key = none if is_snowflake else 'event_id',
        schema = 'gold',
    )
}}

-- Gold (streaming lane): the near-real-time twin of fact_sales.
--
-- Same grain (one row per order line) and the SAME measure formulas as the
-- batch fact — only the freshness differs:
--   revenue         = quantity * unit_price
--   cost_amount     = quantity * unit_cost
--   profit          = revenue - cost_amount
--   discount_amount = quantity * (list_price - unit_price)
--
-- Materialization is the whole point of this model:
--   * Snowflake -> DYNAMIC TABLE with TARGET_LAG='1 minute'. Snowflake keeps it
--     incrementally refreshed on its own; we declare the freshness we want and
--     it figures out how (declarative, the 2026 idiom).
--   * DuckDB    -> INCREMENTAL model (no dynamic tables), refreshed by re-running
--     dbt. Same SQL, so local and CI stay fully offline.
--
-- NOTE: no CURRENT_TIMESTAMP here on purpose — a non-deterministic expression
-- would break Snowflake's incremental refresh. "How fresh is the data *now*" is
-- answered by the separate rt_freshness view, evaluated at query time.
with events as (
    select * from {{ ref('stg_order_events') }}

    {%- if is_incremental() %}
    -- Only the events we have not loaded yet (DuckDB lane; on Snowflake the
    -- dynamic table handles incrementality itself and this block is skipped).
    where event_ts > (select coalesce(max(event_ts), timestamp '1900-01-01') from {{ this }})
    {%- endif %}
),

products as (
    select * from {{ ref('stg_products') }}
)

select
    e.event_id,
    e.order_id,
    e.order_item_id,
    e.customer_id,
    e.product_id,
    e.store_id,
    e.event_ts,
    cast(e.event_ts as date)                    as event_date,
    {{ date_id('cast(e.event_ts as date)') }}   as date_id,     -- FK -> dim_dates
    e.channel,
    e.status,
    e.quantity,
    e.unit_price,
    p.unit_cost,
    cast(e.quantity * e.unit_price as decimal(12, 2))                  as revenue,
    cast(e.quantity * p.unit_cost as decimal(12, 2))                   as cost_amount,
    cast(e.quantity * (e.unit_price - p.unit_cost) as decimal(12, 2))  as profit,
    cast(e.quantity * (p.list_price - e.unit_price) as decimal(12, 2)) as discount_amount,
    (e.status = 'completed') as is_completed,
    (e.status = 'returned')  as is_returned,
    (e.status = 'cancelled') as is_cancelled
from events e
inner join products p on e.product_id = p.product_id
