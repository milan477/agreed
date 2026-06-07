"""Moderation frameworks — swappable rules for how agreement is reached.

Selectable at step 2. Each framework scores candidate proposals so the moderator
can pick a final settlement, and can impose hard constraints (e.g. legal limits).

  - pareto   : collaborative default; maximize joint surplus among non-dominated.
  - rawlsian : fairness-first; maximize the worse-off party's utility (max-min).
  - rules    : domain constraints (e.g. rental law) filter candidates first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .scoring import compute_party_utility, is_pareto_optimal, score_outcome
from .term_sheets import Scenario


@dataclass
class Framework:
    key: str
    name: str
    description: str
    # returns a sortable key; higher is better
    objective: Callable[[dict, Scenario], float]
    # optional hard-constraint filter; returns (ok, reason)
    constraint: Callable[[dict, Scenario], tuple[bool, str]] | None = None

    def feasible(self, terms: dict, scenario: Scenario) -> tuple[bool, str]:
        if self.constraint is None:
            return True, ""
        return self.constraint(terms, scenario)

    def select(self, candidates: list[dict], scenario: Scenario) -> dict | None:
        """Choose the best settlement among candidates under this framework."""
        feasible = [c for c in candidates if self.feasible(c, scenario)[0]]
        pool = feasible or candidates
        if not pool:
            return None
        return max(pool, key=lambda t: self.objective(t, scenario))


def _joint_surplus(terms: dict, scenario: Scenario) -> float:
    return compute_party_utility(terms, "Buyer", scenario) + compute_party_utility(terms, "Seller", scenario)


def _max_min(terms: dict, scenario: Scenario) -> float:
    return min(
        compute_party_utility(terms, "Buyer", scenario),
        compute_party_utility(terms, "Seller", scenario),
    )


def _rules_objective(terms: dict, scenario: Scenario) -> float:
    # Among legally-feasible deals, prefer balanced outcomes (Rawlsian flavor).
    return _max_min(terms, scenario)


def _rental_law_constraint(terms: dict, scenario: Scenario) -> tuple[bool, str]:
    """Example domain constraints. Generic demo guardrails on the B2B scenario:
    enforce a statutory warranty floor and a payment-term ceiling.
    """
    if terms.get("warranty_months", 0) < 12:
        return False, "Statutory minimum warranty is 12 months."
    if terms.get("payment_terms") in ("net80", "net90"):
        return False, "Payment terms beyond net70 are not permitted in this jurisdiction."
    return True, ""


PARETO = Framework(
    key="pareto",
    name="Pareto-optimization",
    description="Collaborative default. Among non-dominated deals, maximize total joint surplus.",
    objective=_joint_surplus,
)

RAWLSIAN = Framework(
    key="rawlsian",
    name="Rawlsian max-min",
    description="Fairness-first. Maximize the utility of the worse-off party.",
    objective=_max_min,
)

RULES = Framework(
    key="rules",
    name="Rules-based legal framework",
    description="Apply hard legal constraints first, then prefer balanced outcomes.",
    objective=_rules_objective,
    constraint=_rental_law_constraint,
)

FRAMEWORKS: dict[str, Framework] = {f.key: f for f in (PARETO, RAWLSIAN, RULES)}


def get_framework(key: str | None) -> Framework:
    return FRAMEWORKS.get((key or "pareto").lower(), PARETO)
