"""Run the routing-accuracy suite against the live agent.

    uv run python -m eval.run_eval     (or: make eval)

Needs ANTHROPIC_API_KEY and a built warehouse (make warehouse). Exits non-zero
if any case fails, so it can gate CI once a key is available. Without a key it
prints a notice and exits 0 — the suite is opt-in, not a hard CI dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.cases import CASES
from governed_analytics_agent.config import settings
from governed_analytics_agent.evaluation import accuracy, format_report, run_suite


def main() -> int:
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY not set — skipping the live eval (set it in .env to run).")
        return 0

    print(f"Running {len(CASES)} routing cases against {settings.anthropic_model}…\n")
    scores = run_suite(CASES)
    print(format_report(scores))

    out = Path(__file__).resolve().parent / "last_run.json"
    out.write_text(
        json.dumps(
            {
                "model": settings.anthropic_model,
                "accuracy": accuracy(scores),
                "cases": [
                    {
                        "question": s.case.question,
                        "expect_metrics": s.case.expect_metrics,
                        "chosen_metrics": s.chosen_metrics,
                        "chosen_group_by": s.chosen_group_by,
                        "passed": s.passed,
                        "note": s.note,
                    }
                    for s in scores
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nWrote results to {out}")
    return 0 if accuracy(scores) == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
