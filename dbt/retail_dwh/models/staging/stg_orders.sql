-- Silver: clean orders.
--   * cast order_date (text in Bronze) -> DATE
--   * normalize channel/status to lowercase enums
with source as (
    select * from {{ source('bronze', 'orders') }}
)

select
    order_id,
    customer_id,
    store_id,
    cast(order_date as date) as order_date,
    lower(trim(channel))     as channel,
    lower(trim(status))      as status
from source
