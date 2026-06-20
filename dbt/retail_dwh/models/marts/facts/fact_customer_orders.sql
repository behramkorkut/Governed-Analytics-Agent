-- Gold summary fact: one row per *purchasing* customer, summarising their order
-- history. Behavioural/lifetime metrics live in facts (not the descriptive
-- customer dimension), so customer-loyalty metrics (repeat-customer rate) build
-- from here. Customers who never ordered do not appear — purchasing customers
-- are exactly the rows of this table, which is the denominator for loyalty.
with orders as (
    select
        customer_id,
        count(distinct order_id) as order_count,
        max(order_date)          as last_order_date
    from {{ ref('stg_orders') }}
    group by customer_id
)

select
    customer_id,
    order_count,
    order_count >= 2 as is_repeat_customer,  -- ordered on more than one occasion
    last_order_date
from orders
