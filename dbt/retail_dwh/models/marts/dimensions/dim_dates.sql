-- Gold dimension: a date spine generated in SQL (no external package).
-- Covers the data range with room to spare. A conformed date dimension
-- lets every fact be analyzed by year/quarter/month/weekday consistently.
--
-- Portable across DuckDB (local/CI) and Snowflake (prod) via macros/portability.sql:
-- the date spine and the date-formatting functions differ between engines; the
-- DuckDB branch reproduces the original SQL exactly, so local output is unchanged.
with spine as (
    {{ date_spine_days('2024-01-01', '2027-01-01') }}
)

select
    {{ date_id('date_day') }}                     as date_id,   -- yyyymmdd surrogate
    date_day,
    extract(year   from date_day)                 as year,
    extract(quarter from date_day)                as quarter,
    'Q' || extract(quarter from date_day)         as quarter_name,
    extract(month  from date_day)                 as month,
    {{ month_name('date_day') }}                  as month_name,
    extract(week   from date_day)                 as week_of_year,
    extract(dayofweek from date_day)              as day_of_week,   -- 0=Sun .. 6=Sat
    {{ day_name('date_day') }}                    as day_name,
    (extract(dayofweek from date_day) in (0, 6))  as is_weekend
from spine
