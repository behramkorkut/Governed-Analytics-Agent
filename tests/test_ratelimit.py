"""Unit tests for the daily per-IP rate limiter (pure, no warehouse)."""

from governed_analytics_agent.ratelimit import (
    WINDOW_S,
    SlidingWindowRateLimiter,
    check_rate_limit,
    reset_rate_limiter,
)


def test_allows_up_to_the_daily_budget_then_blocks():
    limiter = SlidingWindowRateLimiter()
    for _ in range(6):
        allowed, _ = limiter.allow("1.2.3.4", 6)
        assert allowed
    allowed, retry_after = limiter.allow("1.2.3.4", 6)
    assert not allowed
    assert 0 < retry_after <= WINDOW_S


def test_budget_is_per_ip():
    limiter = SlidingWindowRateLimiter()
    for _ in range(6):
        limiter.allow("1.1.1.1", 6)
    assert limiter.allow("2.2.2.2", 6)[0]


def test_window_expires_after_a_day():
    limiter = SlidingWindowRateLimiter()
    t0 = 1_000_000.0
    for i in range(6):
        limiter.allow("1.2.3.4", 6, now=t0 + i)
    assert not limiter.allow("1.2.3.4", 6, now=t0 + 6)[0]
    # one day later, the oldest hit has slid out of the window
    assert limiter.allow("1.2.3.4", 6, now=t0 + WINDOW_S + 1)[0]


def test_zero_disables_the_limit():
    reset_rate_limiter()
    for _ in range(100):
        assert check_rate_limit("1.2.3.4", 0)[0]
