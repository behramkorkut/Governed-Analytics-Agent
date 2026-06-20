"""Token accounting for the agent: tokens, cost, and a tiny pricing table.

The figures the agent returns are deterministic; *running* the agent still costs
money, and an LLM product that can't tell you what it spent is not a serious one.
We accumulate token usage across the tool-use loop and price it from a small,
explicitly dated table. Prices are USD per million tokens.

Source: Anthropic public pricing, cached 2026-06-04. Update PRICES when the
published rates change — keep the date current so the number stays honest.
"""

from __future__ import annotations

from dataclasses import dataclass

# model -> (input $/Mtok, output $/Mtok). Cache reads/writes are priced off the
# input rate (read ~0.1x, write ~1.25x) per Anthropic's caching docs.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

_CACHE_READ_MULT = 0.10
_CACHE_WRITE_MULT = 1.25


@dataclass
class Usage:
    """Token counters accumulated across one agent run (the whole tool loop)."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, resp_usage: object) -> None:
        """Fold one API response's `usage` block into the running total.

        Tolerant by design: a mocked client (used in tests) has no usage, so a
        missing attribute simply contributes nothing.
        """
        if resp_usage is None:
            return
        self.requests += 1
        self.input_tokens += int(getattr(resp_usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(resp_usage, "output_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(resp_usage, "cache_read_input_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(resp_usage, "cache_creation_input_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def cost_usd(self, model: str) -> float | None:
        """Cost of this usage on `model`, or None if the model isn't priced."""
        rates = PRICES.get(model)
        if rates is None:
            return None
        in_rate, out_rate = rates
        cost = (
            self.input_tokens * in_rate
            + self.cache_read_tokens * in_rate * _CACHE_READ_MULT
            + self.cache_write_tokens * in_rate * _CACHE_WRITE_MULT
            + self.output_tokens * out_rate
        ) / 1_000_000
        return round(cost, 6)
