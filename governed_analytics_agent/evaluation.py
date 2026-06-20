"""Evaluation harness for the governed agent's *routing* accuracy.

"How do you know the agent is correct?" is the question this answers. The figures
are deterministic, but the agent still has to map a natural-language question to
the right metric(s) and grouping. This harness runs a labelled set of questions
through the agent and checks the metric selection it chose against the expected
one — turning "it seems to work" into a measurable number.

The scoring (`score_case`) is pure and unit-tested without any LLM. The runner
(`run_suite`) drives the real agent and needs an API key; see eval/run_eval.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .guardrails import MetricQuery


@dataclass(frozen=True)
class EvalCase:
    """One labelled question: what metric selection a correct agent should make."""

    question: str
    expect_metrics: list[str]
    # Optional: dimensions the answer must be grouped by (subset match, so the
    # agent may add more). Time dims may carry a grain, e.g. metric_time__month.
    expect_group_by: list[str] = field(default_factory=list)


@dataclass
class CaseScore:
    case: EvalCase
    chosen_metrics: list[str]
    chosen_group_by: list[str]
    metrics_ok: bool
    group_by_ok: bool
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.metrics_ok and self.group_by_ok


def score_case(case: EvalCase, query: MetricQuery | None) -> CaseScore:
    """Compare the agent's chosen query against the expected selection.

    Metrics must match exactly (a wrong or extra metric is a routing error).
    Grouping is a subset check: the agent must include every expected dimension
    but may add others. A None query (the agent answered nothing) fails both.
    """
    if query is None:
        return CaseScore(case, [], [], False, False, note="agent produced no query")

    metrics_ok = set(case.expect_metrics) == set(query.metrics)
    group_by_ok = set(case.expect_group_by).issubset(set(query.group_by))
    note = ""
    if not metrics_ok:
        note = f"expected metrics {sorted(case.expect_metrics)}, got {sorted(query.metrics)}"
    elif not group_by_ok:
        note = f"expected group_by ⊇ {sorted(case.expect_group_by)}, got {sorted(query.group_by)}"
    return CaseScore(
        case=case,
        chosen_metrics=list(query.metrics),
        chosen_group_by=list(query.group_by),
        metrics_ok=metrics_ok,
        group_by_ok=group_by_ok,
        note=note,
    )


def accuracy(scores: list[CaseScore]) -> float:
    """Share of cases that passed (0.0 to 1.0). Empty input is 0.0."""
    if not scores:
        return 0.0
    return sum(s.passed for s in scores) / len(scores)


def run_suite(cases: list[EvalCase], agent=None) -> list[CaseScore]:
    """Run every case through the agent and score it. Requires an API key.

    `agent` is injectable for testing; by default a real GovernedAnalyticsAgent
    is constructed (which checks for ANTHROPIC_API_KEY).
    """
    if agent is None:
        from .agent import GovernedAnalyticsAgent

        agent = GovernedAnalyticsAgent()
    scores = []
    for case in cases:
        result = agent.run(case.question)
        scores.append(score_case(case, result.query))
    return scores


def format_report(scores: list[CaseScore]) -> str:
    """A compact, terminal-friendly scorecard."""
    lines = []
    for s in scores:
        mark = "PASS" if s.passed else "FAIL"
        line = f"  [{mark}] {s.case.question}"
        if not s.passed:
            line += f"\n         → {s.note}"
        lines.append(line)
    acc = accuracy(scores)
    passed = sum(s.passed for s in scores)
    lines.append(f"\nRouting accuracy: {passed}/{len(scores)} = {acc:.0%}")
    return "\n".join(lines)
