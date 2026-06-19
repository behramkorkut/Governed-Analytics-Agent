-- Gold dimension: store attributes.
select
    store_id,
    store_name,
    country,
    city
from {{ ref('stg_stores') }}
