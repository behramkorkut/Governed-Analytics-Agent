-- Silver: order line items (the future grain of the fact table).
with source as (
    select * from {{ source('bronze', 'order_items') }}
)

select
    order_item_id,
    order_id,
    product_id,
    cast(quantity as integer)           as quantity,
    cast(unit_price as decimal(10, 2))  as unit_price
from source
