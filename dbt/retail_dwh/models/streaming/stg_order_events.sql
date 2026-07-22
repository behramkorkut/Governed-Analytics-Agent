-- Silver (streaming lane): clean the raw order events landed by the producer.
--
-- Same contract as the batch staging models — cast and conform, nothing more:
--   * normalize channel/status to lowercase enums (identical to stg_orders)
--   * cast the numeric measures
--   * keep event_ts as a real TIMESTAMP: it is the whole point of this lane,
--     the batch equivalent (order_date) is only day-grain.
with source as (
    select * from {{ source('bronze', 'order_events') }}
)

select
    event_id,
    order_id,
    order_item_id,
    customer_id,
    store_id,
    product_id,
    cast(quantity as integer)          as quantity,
    cast(unit_price as decimal(10, 2)) as unit_price,
    lower(trim(channel))               as channel,
    lower(trim(status))                as status,
    cast(event_ts as timestamp)        as event_ts
from source
