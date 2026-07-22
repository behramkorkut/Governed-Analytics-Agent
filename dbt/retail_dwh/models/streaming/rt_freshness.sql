{{ config(materialized='view', schema='gold') }}

-- Freshness of the near-real-time lane, evaluated AT QUERY TIME.
--
-- This is deliberately a VIEW, not a table: current_timestamp must be read when
-- the question is asked, so "how fresh is the data *now*" is honest. Baking an
-- age column into fact_sales_live would freeze it at the last refresh and also
-- break Snowflake's incremental dynamic-table refresh (non-deterministic expr).
--
-- One row: the latest event seen, and how many seconds ago that was.
with latest as (
    select max(event_ts) as last_event_ts
    from {{ ref('stg_order_events') }}
)

select
    last_event_ts,
    current_timestamp                                              as as_of,
    datediff('second', last_event_ts, current_timestamp)           as freshness_seconds,
    (last_event_ts is null)                                        as no_events_yet
from latest
