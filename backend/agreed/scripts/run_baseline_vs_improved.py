"""Headline demo: baseline vs. self-improved negotiation.

Runs an eval suite with default strategy, then the self-improvement agent
optimizes the buyer's strategy (reading traces + self-play), then re-runs the
suite. The eval metric measurably improves.

    python -m agreed.scripts.run_baseline_vs_improved
"""

from __future__ import annotations

from ..agents.self_improve import SelfImprovementAgent
from ..config import capability_report
from ..evals.evaluations import run_eval_suite
from ..observability import init_observability, weave_trace_url


def _row(label: str, s) -> str:
    return (
        f"{label:10} | closure {s.deal_closure_rate:>5.0%} | buyer {s.avg_buyer_utility:>5.1f} | "
        f"seller {s.avg_seller_utility:>5.1f} | joint {s.avg_joint_surplus:>6.1f} | "
        f"min {s.avg_min_utility:>5.1f} | pareto {s.pareto_rate:>4.0%} | bias {s.bias_divergence:>4.2f}"
    )


def main() -> None:
    init_observability()
    print("=" * 96)
    print("  agreed — self-improvement demo (baseline vs improved)")
    print("=" * 96)
    print("  backend:", capability_report()["llm_backend"], "| weave:", capability_report()["weave"])
    print("-" * 96)

    n = 5
    baseline = run_eval_suite(framework="pareto", n=n)
    print(_row("BASELINE", baseline))

    improver = SelfImprovementAgent()
    diag = improver.read_traces()
    print(f"\n  self-improvement: reading traces ({diag['source']}) -> {diag.get('diagnosis')}")
    opt = improver.optimize_strategy("Buyer", framework="pareto", metric="party_utility")
    print(f"  optimized buyer strategy (DSPy={opt['used_dspy']}): "
          f"{opt['baseline_metric']} -> {opt['improved_metric']} (+{opt['improvement']})")
    print(f"    params: {opt['improved_strategy']}")

    improved = run_eval_suite(framework="pareto", buyer_strategy=opt["strategy"], n=n)
    print()
    print(_row("BASELINE", baseline))
    print(_row("IMPROVED", improved))

    delta = round(improved.avg_buyer_utility - baseline.avg_buyer_utility, 2)
    djoint = round(improved.avg_joint_surplus - baseline.avg_joint_surplus, 2)
    print("-" * 96)
    print(f"  RESULT: buyer utility {'+' if delta >= 0 else ''}{delta}, "
          f"joint surplus {'+' if djoint >= 0 else ''}{djoint} after self-improvement.")
    url = weave_trace_url()
    if url:
        print(f"  Weave dashboard: {url}")


if __name__ == "__main__":
    main()
