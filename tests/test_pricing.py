"""Unit tests for token accounting and cost (pure)."""

from types import SimpleNamespace as NS

from governed_analytics_agent.pricing import Usage


def test_cost_sonnet_per_million():
    # Sonnet 4.6 is $3 in / $15 out per 1M tokens.
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert u.cost_usd("claude-sonnet-4-6") == 18.0


def test_cache_read_is_discounted():
    # 1M cache-read tokens cost 0.1x the input rate ($3 -> $0.30).
    u = Usage(cache_read_tokens=1_000_000)
    assert u.cost_usd("claude-sonnet-4-6") == 0.30


def test_unknown_model_returns_none():
    assert Usage(input_tokens=100).cost_usd("not-a-model") is None


def test_add_tolerates_missing_usage():
    u = Usage()
    u.add(None)  # mocked clients have no usage block
    assert u.requests == 0 and u.total_tokens == 0


def test_add_accumulates_across_requests():
    u = Usage()
    u.add(NS(input_tokens=10, output_tokens=5))
    u.add(NS(input_tokens=20, output_tokens=5, cache_read_input_tokens=100))
    assert u.requests == 2
    assert u.input_tokens == 30 and u.output_tokens == 10 and u.cache_read_tokens == 100
    assert u.total_tokens == 140
