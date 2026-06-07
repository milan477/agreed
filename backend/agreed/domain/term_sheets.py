"""Negotiation scenario definitions.

Ported from the original `example.ipynb` prototype. A scenario defines the
negotiable dimensions and each party's private term sheet (priorities, targets,
walk-away limits, utility weights). Asymmetric priorities create room for
Pareto-improving trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIMENSIONS = ("price", "delivery_weeks", "payment_terms", "warranty_months", "support_hours")
PAYMENT_ORDER = ["net30", "net40", "net50", "net60", "net70", "net80", "net90"]

DIM_LABELS = {
    "price": "Price",
    "delivery_weeks": "Delivery",
    "payment_terms": "Payment",
    "warranty_months": "Warranty",
    "support_hours": "Support",
}


BUYER_TERM_SHEET: dict = {
    "role": "Buyer",
    "description": "You are purchasing a custom software platform.",
    "priority_ranking": ["price", "warranty_months", "payment_terms", "delivery_weeks", "support_hours"],
    "priorities": (
        "1) price (MUST be low - your #1 issue), "
        "2) warranty_months (longer is much better), "
        "3) payment_terms (longer is better), "
        "4) delivery_weeks (flexible - low priority), "
        "5) support_hours (barely care)"
    ),
    "limits": {
        "price": {"walk_away": 90_000, "target": 65_000},
        "delivery_weeks": {"walk_away": 20, "target": 10},
        "payment_terms": {"acceptable": PAYMENT_ORDER, "target": "net60"},
        "warranty_months": {"walk_away": 6, "target": 24},
        "support_hours": {"walk_away": 20, "target": 160},
    },
    "weights": {
        "price": 0.45,
        "warranty_months": 0.25,
        "payment_terms": 0.15,
        "delivery_weeks": 0.10,
        "support_hours": 0.05,
    },
}

SELLER_TERM_SHEET: dict = {
    "role": "Seller",
    "description": "You are selling a custom software platform.",
    "priority_ranking": ["delivery_weeks", "support_hours", "price", "payment_terms", "warranty_months"],
    "priorities": (
        "1) delivery_weeks (MUST have enough time - your #1 issue), "
        "2) support_hours (fewer included hours is much better - limits unpaid scope), "
        "3) price (higher is better), "
        "4) payment_terms (flexible), "
        "5) warranty_months (barely care)"
    ),
    "limits": {
        "price": {"walk_away": 60_000, "target": 80_000},
        "delivery_weeks": {"walk_away": 8, "target": 16},
        "payment_terms": {"acceptable": PAYMENT_ORDER, "target": "net30"},
        "warranty_months": {"walk_away": 24, "target": 6},
        "support_hours": {"walk_away": 200, "target": 40},
    },
    "weights": {
        "delivery_weeks": 0.40,
        "support_hours": 0.30,
        "price": 0.15,
        "payment_terms": 0.10,
        "warranty_months": 0.05,
    },
}


@dataclass
class Scenario:
    """A negotiable scenario: dimensions + both parties' private term sheets."""

    key: str
    title: str
    dimensions: tuple[str, ...]
    buyer: dict
    seller: dict
    description: str = ""

    def term_sheet(self, role: str) -> dict:
        return self.buyer if role == "Buyer" else self.seller


DEFAULT_SCENARIO = Scenario(
    key="b2b_software",
    title="Custom software platform — B2B contract",
    dimensions=DIMENSIONS,
    buyer=BUYER_TERM_SHEET,
    seller=SELLER_TERM_SHEET,
    description=(
        "A buyer purchases a custom software platform from a seller. Five "
        "dimensions are negotiable with asymmetric private priorities, leaving "
        "room for mutually beneficial (Pareto-improving) trades."
    ),
)

SCENARIOS: dict[str, Scenario] = {DEFAULT_SCENARIO.key: DEFAULT_SCENARIO}


def get_scenario(key: str | None = None) -> Scenario:
    if not key:
        return DEFAULT_SCENARIO
    return SCENARIOS.get(key, DEFAULT_SCENARIO)
