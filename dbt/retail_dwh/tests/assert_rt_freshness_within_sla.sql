{{ config(severity='warn') }}

-- Freshness SLA for the near-real-time lane.
--
-- Returns a row (a test failure) only when live data EXISTS and is staler than
-- the SLA (default 120s, override with --vars 'rt_freshness_sla_seconds: N').
--
-- Kept at severity=warn on purpose:
--   * CI never runs the streaming producer, so the lane is legitimately empty
--     there (no_events_yet -> no row -> passes anyway);
--   * even locally, freshness grows naturally between producer runs, so a hard
--     error would be noise. For a live demo, bump it to 'error' via config to
--     make the SLA a gate.
select
    freshness_seconds,
    last_event_ts
from {{ ref('rt_freshness') }}
where no_events_yet = false
  and freshness_seconds > {{ var('rt_freshness_sla_seconds', 120) }}
