-- Gold dimension: a date spine generated in SQL (no external package).
-- Covers the data range with room to spare. A conformed date dimension
-- lets every fact be analyzed by year/quarter/month/weekday consistently.
with spine as (
    select cast(d as date) as date_day
    from range(date '2024-01-01', date '2027-01-01', interval 1 day) as t(d)
)

select
    cast(strftime(date_day, '%Y%m%d') as integer) as date_id,   -- yyyymmdd surrogate
    date_day,
    extract(year   from date_day)                 as year,
    extract(quarter from date_day)                as quarter,
    'Q' || extract(quarter from date_day)         as quarter_name,
    extract(month  from date_day)                 as month,
    strftime(date_day, '%B')                      as month_name,
    extract(week   from date_day)                 as week_of_year,
    extract(dayofweek from date_day)              as day_of_week,   -- 0=Sun .. 6=Sat
    strftime(date_day, '%A')                      as day_name,
    (extract(dayofweek from date_day) in (0, 6))  as is_weekend
from spine
