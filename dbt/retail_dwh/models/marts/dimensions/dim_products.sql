-- Gold dimension: product attributes + a simple margin-rate classification.
select
    product_id,
    product_name,
    category,
    unit_cost,
    list_price,
    unit_margin,
    round(unit_margin / nullif(list_price, 0), 4) as margin_rate
from {{ ref('stg_products') }}
