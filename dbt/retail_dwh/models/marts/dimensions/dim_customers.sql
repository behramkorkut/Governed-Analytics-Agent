-- Gold dimension: descriptive customer attributes for slicing/grouping.
-- Kept purely descriptive (Kimball) — lifetime metrics belong to the
-- semantic layer / facts, not to the dimension.
select
    customer_id,
    first_name,
    last_name,
    first_name || ' ' || last_name as full_name,
    email,
    country,
    city,
    signup_date
from {{ ref('stg_customers') }}
