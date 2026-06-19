-- Silver: clean stores (countries are already canonical at source here).
with source as (
    select * from {{ source('bronze', 'stores') }}
)

select
    store_id,
    trim(store_name) as store_name,
    trim(country)    as country,
    trim(city)       as city
from source
