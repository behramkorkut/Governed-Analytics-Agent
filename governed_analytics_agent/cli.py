"""Terminal entry point for the governed analytics agent.

Usage:
    uv run python -m governed_analytics_agent.cli "What is revenue by category?"
    uv run python -m governed_analytics_agent.cli           # interactive REPL
"""

from __future__ import annotations

import sys

from .agent import GovernedAnalyticsAgent


def _print_result(res) -> None:
    print("\n" + res.answer + "\n")
    if res.query:
        print(f"  metrics : {res.query.metrics}")
        print(f"  group_by: {res.query.group_by}")
        print(f"  rows    : {len(res.rows)}")
    cost = res.cost_usd
    cost_txt = f"${cost:.4f}" if cost is not None else "n/a"
    print(f"  cost    : {res.latency_s:.1f}s · {res.usage.total_tokens:,} tokens · {cost_txt}")
    if res.fabrication_flags:
        print(f"  ⚠ cited figures not found in the data: {res.fabrication_flags}")


def main() -> None:
    agent = GovernedAnalyticsAgent()  # loads catalog, checks API key
    question = " ".join(sys.argv[1:]).strip()

    if question:
        _print_result(agent.run(question))
        return

    print("Governed analytics agent — ask a business question (Ctrl-D to quit).")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q:
            _print_result(agent.run(q))


if __name__ == "__main__":
    main()
