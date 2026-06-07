"""Moderator agent — enforces the framework, manages turn-taking, and proposes a
final settlement that is optimal under the chosen moderation framework.

Optional: only instantiated if the inviting party specifies a moderator in the
moderation framework. When absent, agents close on their own acceptance.
"""

from __future__ import annotations

import copy

from ..domain.frameworks import Framework
from ..domain.scoring import compute_party_utility, is_pareto_optimal, score_outcome
from ..domain.term_sheets import DIMENSIONS, PAYMENT_ORDER, Scenario
from ..observability import op
from .base import Agent
from .critic import CriticAgent


class ModeratorAgent(Agent):
    role = "moderator"

    def __init__(self, scenario: Scenario, framework: Framework, max_rounds: int = 12):
        super().__init__(name="moderator")
        self.scenario = scenario
        self.framework = framework
        self.max_rounds = max_rounds
        self.critic = CriticAgent(scenario)

    @op(name="moderator.check_proposal", kind="agent")
    def check_proposal(self, terms: dict) -> dict:
        """Enforce framework hard constraints on a proposal."""
        ok, reason = self.framework.feasible(terms, self.scenario)
        return {"feasible": ok, "reason": reason, "framework": self.framework.key}

    @op(name="moderator.candidate_frontier", kind="agent")
    def candidate_frontier(self, history: list[dict]) -> list[dict]:
        """Build candidate settlements: all proposed terms plus midpoint blends,
        then keep the Pareto-non-dominated set."""
        proposed = [copy.deepcopy(e["terms"]) for e in history if e.get("terms")]
        # add pairwise midpoints to densify the frontier
        blended: list[dict] = []
        for i in range(len(proposed)):
            for j in range(i + 1, len(proposed)):
                a, b = proposed[i], proposed[j]
                mid = {}
                for d in DIMENSIONS:
                    if d == "payment_terms":
                        ai, bi = PAYMENT_ORDER.index(a[d]), PAYMENT_ORDER.index(b[d])
                        mid[d] = PAYMENT_ORDER[(ai + bi) // 2]
                    else:
                        mid[d] = round((a[d] + b[d]) / 2)
                blended.append(mid)
        candidates = proposed + blended
        # dedupe
        seen, unique = set(), []
        for c in candidates:
            key = tuple(c[d] for d in DIMENSIONS)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        frontier = [c for c in unique if is_pareto_optimal(c, unique, self.scenario)]
        return frontier or unique

    @op(name="moderator.propose_settlement", kind="agent")
    def propose_settlement(self, history: list[dict], agreed_terms: dict | None = None) -> dict:
        """Select the final settlement under the active framework.

        If the parties already agreed on terms, the moderator verifies feasibility
        and reports whether a strictly better deal exists on the frontier.
        """
        frontier = self.candidate_frontier(history)
        chosen = self.framework.select(frontier, self.scenario)

        result = {
            "framework": self.framework.key,
            "framework_name": self.framework.name,
            "settlement": chosen,
            "settlement_score": self.critic.evaluate(chosen) if chosen else None,
            "frontier_size": len(frontier),
        }
        if agreed_terms is not None:
            ok, reason = self.framework.feasible(agreed_terms, self.scenario)
            result["agreed_terms"] = agreed_terms
            result["agreed_score"] = self.critic.evaluate(agreed_terms)
            result["agreed_feasible"] = ok
            result["agreed_feasible_reason"] = reason
            # Does the framework's pick improve on what the parties agreed to?
            if chosen:
                a, c = result["agreed_score"], result["settlement_score"]
                result["improvement_available"] = c[self._obj_key()] > a[self._obj_key()]
        return result

    def _obj_key(self) -> str:
        return "min_utility" if self.framework.key == "rawlsian" else "joint_surplus"
