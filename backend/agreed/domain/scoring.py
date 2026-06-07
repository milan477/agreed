"""Utility functions and Pareto analysis.

Ported from `example.ipynb`. Each party has an explicit numerical utility
function (weighted per-dimension scores in [0, 100]). The moderator/critic use
these to find Pareto-optimal proposals and to show "both parties moved up and to
the right" in the demo.
"""

from __future__ import annotations

from .term_sheets import PAYMENT_ORDER, Scenario


def payment_utility() -> dict[str, float]:
    n = len(PAYMENT_ORDER) - 1
    return {term: i * 100 / n for i, term in enumerate(PAYMENT_ORDER)}


def dim_score(value: float, target: float, walk_away: float, higher_is_better: bool) -> float:
    if target == walk_away:
        return 50.0
    if higher_is_better:
        return max(0.0, min(100.0, (value - walk_away) / (target - walk_away) * 100))
    return max(0.0, min(100.0, (walk_away - value) / (walk_away - target) * 100))


def party_dimension_scores(terms: dict, party: str, scenario: Scenario) -> dict[str, float]:
    pay_val = payment_utility()
    bl, sl = scenario.buyer["limits"], scenario.seller["limits"]

    if party == "Buyer":
        return {
            "price": dim_score(terms["price"], bl["price"]["target"], bl["price"]["walk_away"], False),
            "warranty_months": dim_score(
                terms["warranty_months"], bl["warranty_months"]["target"], bl["warranty_months"]["walk_away"], True
            ),
            "payment_terms": pay_val.get(terms["payment_terms"], 0),
            "delivery_weeks": dim_score(
                terms["delivery_weeks"], bl["delivery_weeks"]["target"], bl["delivery_weeks"]["walk_away"], False
            ),
            "support_hours": dim_score(
                terms["support_hours"], bl["support_hours"]["target"], bl["support_hours"]["walk_away"], True
            ),
        }
    return {
        "delivery_weeks": dim_score(
            terms["delivery_weeks"], sl["delivery_weeks"]["target"], sl["delivery_weeks"]["walk_away"], True
        ),
        "support_hours": dim_score(
            terms["support_hours"], sl["support_hours"]["target"], sl["support_hours"]["walk_away"], False
        ),
        "price": dim_score(terms["price"], sl["price"]["target"], sl["price"]["walk_away"], True),
        "payment_terms": 100 - pay_val.get(terms["payment_terms"], 0),
        "warranty_months": dim_score(
            terms["warranty_months"], sl["warranty_months"]["target"], sl["warranty_months"]["walk_away"], False
        ),
    }


def compute_party_utility(terms: dict, party: str, scenario: Scenario) -> float:
    dims = party_dimension_scores(terms, party, scenario)
    weights = scenario.term_sheet(party)["weights"]
    return sum(dims[d] * weights[d] for d in weights)


def score_outcome(terms: dict | None, scenario: Scenario) -> dict | None:
    if not terms:
        return None

    buyer_total = compute_party_utility(terms, "Buyer", scenario)
    seller_total = compute_party_utility(terms, "Seller", scenario)

    return {
        "buyer_score": round(buyer_total, 1),
        "seller_score": round(seller_total, 1),
        "joint_surplus": round(buyer_total + seller_total, 1),
        # Rawlsian/fairness lens: the worse-off party's utility.
        "min_utility": round(min(buyer_total, seller_total), 1),
        "utility_gap": round(abs(buyer_total - seller_total), 1),
        "components": {
            "buyer": {k: round(v, 1) for k, v in party_dimension_scores(terms, "Buyer", scenario).items()},
            "seller": {k: round(v, 1) for k, v in party_dimension_scores(terms, "Seller", scenario).items()},
        },
    }


def dominates(a: dict, b: dict, scenario: Scenario) -> bool:
    """True if terms `a` Pareto-dominate `b` (>= for both, > for at least one)."""
    ab = compute_party_utility(a, "Buyer", scenario)
    as_ = compute_party_utility(a, "Seller", scenario)
    bb = compute_party_utility(b, "Buyer", scenario)
    bs = compute_party_utility(b, "Seller", scenario)
    return (ab >= bb and as_ >= bs) and (ab > bb or as_ > bs)


def is_pareto_optimal(terms: dict, candidates: list[dict], scenario: Scenario) -> bool:
    """Whether `terms` is non-dominated within a candidate set."""
    return not any(dominates(c, terms, scenario) for c in candidates if c != terms)
