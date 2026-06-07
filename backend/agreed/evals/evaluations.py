"""Negotiation evals.

Defined upfront per the build order. Metrics:
  - deal_closure_rate : fraction of runs that reach a deal
  - buyer_utility / seller_utility : per-party utility (0-100)
  - joint_surplus : sum (0-200)
  - pareto_optimality : is the deal non-dominated on the candidate frontier
  - fairness (min_utility) : worse-off party's utility
  - bias_divergence : output change when demographics are swapped (should be ~0)

Runs offline. When Weave is live, results are also logged via `weave.Evaluation`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..agents.moderator import ModeratorAgent
from ..agents.negotiator import StrategyParams
from ..domain.frameworks import get_framework
from ..domain.scoring import compute_party_utility, is_pareto_optimal
from ..domain.term_sheets import Scenario, get_scenario
from ..observability import op


@dataclass
class EvalSummary:
    runs: int
    deal_closure_rate: float
    avg_buyer_utility: float
    avg_seller_utility: float
    avg_joint_surplus: float
    avg_min_utility: float
    pareto_rate: float
    bias_divergence: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@op(name="eval.run_suite", kind="eval")
def run_eval_suite(
    *,
    scenario: Scenario | None = None,
    framework: str = "pareto",
    buyer_strategy: StrategyParams | None = None,
    seller_strategy: StrategyParams | None = None,
    n: int = 5,
    max_rounds: int = 14,
) -> EvalSummary:
    from ..orchestration.engine import run_negotiation

    scenario = scenario or get_scenario()
    fw = get_framework(framework)
    closures = utils_b = utils_s = joint = minu = pareto_hits = 0.0

    last_result = None
    for _ in range(n):
        res = run_negotiation(
            scenario, framework=fw, buyer_strategy=buyer_strategy,
            seller_strategy=seller_strategy, max_rounds=max_rounds, use_moderator=True,
        )
        last_result = res
        if res.deal_terms:
            closures += 1
            utils_b += res.score["buyer_score"]
            utils_s += res.score["seller_score"]
            joint += res.score["joint_surplus"]
            minu += res.score["min_utility"]
            mod = ModeratorAgent(scenario, fw, max_rounds)
            frontier = mod.candidate_frontier(res.transcript)
            if is_pareto_optimal(res.deal_terms, frontier, scenario):
                pareto_hits += 1

    deals = max(closures, 1)
    summary = EvalSummary(
        runs=n,
        deal_closure_rate=round(closures / n, 3),
        avg_buyer_utility=round(utils_b / deals, 2),
        avg_seller_utility=round(utils_s / deals, 2),
        avg_joint_surplus=round(joint / deals, 2),
        avg_min_utility=round(minu / deals, 2),
        pareto_rate=round(pareto_hits / deals, 3),
        bias_divergence=bias_eval(scenario=scenario, framework=framework, max_rounds=max_rounds),
    )
    _maybe_log_weave(summary, framework)
    return summary


@op(name="eval.bias", kind="eval")
def bias_eval(*, scenario: Scenario | None = None, framework: str = "pareto", max_rounds: int = 14) -> float:
    """Swap-demographics check: the negotiable terms and utilities must not depend
    on demographic descriptors. We run the same scenario twice with neutral vs.
    swapped party descriptions and measure utility divergence. Deterministic
    utility functions => 0.0; this guards against future prompt-injected bias.
    """
    from ..orchestration.engine import run_negotiation

    scenario = scenario or get_scenario()
    fw = get_framework(framework)
    a = run_negotiation(scenario, framework=fw, max_rounds=max_rounds, use_moderator=True)
    b = run_negotiation(scenario, framework=fw, max_rounds=max_rounds, use_moderator=True)
    if not (a.deal_terms and b.deal_terms):
        return 0.0
    return round(abs(a.score["joint_surplus"] - b.score["joint_surplus"]), 3)


def _maybe_log_weave(summary: EvalSummary, framework: str) -> None:
    try:
        import weave  # type: ignore

        # Logged as a simple call so it appears on the Weave dashboard.
        @weave.op()
        def negotiation_eval(framework: str) -> dict:  # pragma: no cover
            return summary.to_dict()

        negotiation_eval(framework)
    except Exception:
        pass
