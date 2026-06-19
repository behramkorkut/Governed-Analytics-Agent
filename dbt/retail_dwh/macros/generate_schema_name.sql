{#
    Override dbt's default schema naming.

    By default dbt prefixes custom schemas with the target schema
    (e.g. "main_silver"). We want the clean Medallion names "silver"
    and "gold". This macro returns the custom schema name as-is.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
