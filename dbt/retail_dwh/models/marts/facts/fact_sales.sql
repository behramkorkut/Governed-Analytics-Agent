-- Gold fact: one row per order line (the grain). Joins items -> orders ->
-- products to bring in the foreign keys and compute additive measures.
--
-- Measures (all additive, the property that makes a star schema fast):
--   revenue          = quantity * unit_price (price actually charged)
--   cost_amount      = quantity * unit_cost
--   profit           = revenue - cost_amount
--   discount_amount  = quantity * (list_price - unit_price)
with items as (
    select * from {{ ref('stg_order_items') }}
),
orders as (
    select * from {{ ref('stg_orders') }}
),
products as (
    select * from {{ ref('stg_products') }}
)

select
    i.order_item_id                                       as sales_id,        -- PK (degenerate)
    i.order_id,
    o.customer_id,
    i.product_id,
    o.store_id,
    o.order_date,
    cast(strftime(o.order_date, '%Y%m%d') as integer)     as date_id,         -- FK -> dim_dates
    o.channel,
    o.status,
    i.quantity,
    i.unit_price,
    p.unit_cost,
    cast(i.quantity * i.unit_price as decimal(12, 2))                 as revenue,
    cast(i.quantity * p.unit_cost as decimal(12, 2))                  as cost_amount,
    cast(i.quantity * (i.unit_price - p.unit_cost) as decimal(12, 2)) as profit,
    cast(i.quantity * (p.list_price - i.unit_price) as decimal(12, 2)) as discount_amount,
    (o.status = 'completed') as is_completed,
    (o.status = 'returned')  as is_returned,
    (o.status = 'cancelled') as is_cancelled
from items i
inner join orders o   on i.order_id   = o.order_id
inner join products p  on i.product_id = p.product_id
