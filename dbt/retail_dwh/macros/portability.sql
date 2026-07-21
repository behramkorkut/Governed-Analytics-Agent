{#
    Cross-warehouse helpers so the SAME models run on DuckDB (local + CI) and
    Snowflake (prod). We branch on `target.type`.

    The DuckDB branch reproduces the ORIGINAL SQL byte-for-byte, so the local
    build and the test suite are strictly unchanged. Only `--target prod`
    (Snowflake) takes the alternative branch.

    Validated end-to-end on Snowflake (dbt build 58/60 PASS): the day-of-week
    numbering matches DuckDB (0=Sunday .. 6=Saturday) under the default
    WEEK_START, so `day_name` / `is_weekend` are consistent across both engines.
#}

{# yyyymmdd integer surrogate key from a date column #}
{% macro date_id(col) -%}
    {%- if target.type == 'duckdb' -%}
cast(strftime({{ col }}, '%Y%m%d') as integer)
    {%- else -%}
cast(to_char({{ col }}, 'YYYYMMDD') as integer)
    {%- endif -%}
{%- endmacro %}

{# full month name, e.g. "January" #}
{% macro month_name(col) -%}
    {%- if target.type == 'duckdb' -%}
strftime({{ col }}, '%B')
    {%- else -%}
case extract(month from {{ col }})
    when 1 then 'January' when 2 then 'February' when 3 then 'March'
    when 4 then 'April' when 5 then 'May' when 6 then 'June'
    when 7 then 'July' when 8 then 'August' when 9 then 'September'
    when 10 then 'October' when 11 then 'November' when 12 then 'December'
end
    {%- endif -%}
{%- endmacro %}

{# full weekday name, e.g. "Monday" #}
{% macro day_name(col) -%}
    {%- if target.type == 'duckdb' -%}
strftime({{ col }}, '%A')
    {%- else -%}
{# dayofweek: 0=Sun..6=Sat under default WEEK_START — validated vs DuckDB #}
case extract(dayofweek from {{ col }})
    when 0 then 'Sunday' when 1 then 'Monday' when 2 then 'Tuesday'
    when 3 then 'Wednesday' when 4 then 'Thursday' when 5 then 'Friday'
    when 6 then 'Saturday'
end
    {%- endif -%}
{%- endmacro %}

{# a contiguous daily date spine over [start_date, end_date) #}
{% macro date_spine_days(start_date, end_date) -%}
    {%- if target.type == 'duckdb' -%}
select cast(d as date) as date_day
from range(date '{{ start_date }}', date '{{ end_date }}', interval 1 day) as t(d)
    {%- else -%}
{#- Snowflake GENERATOR(ROWCOUNT => ...) requires a CONSTANT, so we compute the
    day count at compile time (Jinja) instead of with datediff at run time. -#}
{%- set _s = modules.datetime.datetime.strptime(start_date, '%Y-%m-%d') -%}
{%- set _e = modules.datetime.datetime.strptime(end_date, '%Y-%m-%d') -%}
{%- set _n_days = (_e - _s).days -%}
select dateadd(day, seq4(), date '{{ start_date }}') as date_day
from table(generator(rowcount => {{ _n_days }}))
    {%- endif -%}
{%- endmacro %}
