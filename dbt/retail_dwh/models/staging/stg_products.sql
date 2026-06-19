-- Silver: clean products + derive a unit-level margin (a measure we can
-- reuse downstream). Pricing is kept as-is; cost/price come from source.
with source as (
    select * from {{ source('bronze', 'products') }}
)

select
    product_id,
    trim(product_name)                       as product_name,
    category,
    cast(unit_cost as decimal(10, 2))        as unit_cost,
    cast(list_price as decimal(10, 2))       as list_price,
    cast(list_price - unit_cost as decimal(10, 2)) as unit_margin
from source
