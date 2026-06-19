-- Silver: clean & conform raw customers.
--   * cast signup_date (text in Bronze) -> DATE
--   * standardize the ~20 country spellings back to a canonical name
--   * trim names, lowercase emails, replace missing city with 'Unknown'
with source as (
    select * from {{ source('bronze', 'customers') }}
)

select
    customer_id,
    trim(first_name)                                  as first_name,
    trim(last_name)                                   as last_name,
    lower(trim(email))                                as email,
    case upper(trim(country))
        when 'FRANCE'      then 'France'
        when 'FR'          then 'France'
        when 'FRA'         then 'France'
        when 'GERMANY'     then 'Germany'
        when 'DE'          then 'Germany'
        when 'DEUTSCHLAND' then 'Germany'
        when 'SPAIN'       then 'Spain'
        when 'ES'          then 'Spain'
        when 'ESPAÑA'      then 'Spain'
        when 'ITALY'       then 'Italy'
        when 'IT'          then 'Italy'
        when 'ITALIA'      then 'Italy'
        when 'BELGIUM'     then 'Belgium'
        when 'BE'          then 'Belgium'
        when 'BELGIQUE'    then 'Belgium'
        else 'Other'
    end                                               as country,
    coalesce(nullif(trim(city), ''), 'Unknown')       as city,
    cast(signup_date as date)                         as signup_date
from source
