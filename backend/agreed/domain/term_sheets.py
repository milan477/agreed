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


# Buyer-side preference direction per dimension ("low" = lower value is better).
BUYER_DIRECTION = {
    "price": "low",
    "delivery_weeks": "low",
    "warranty_months": "high",
    "support_hours": "high",
}

# A plausible counterparty (seller) weighting that is asymmetric to most buyers,
# which is what creates room for mutually beneficial trades.
_COUNTERPARTY_WEIGHTS = {
    "delivery_weeks": 0.40,
    "support_hours": 0.30,
    "price": 0.15,
    "payment_terms": 0.10,
    "warranty_months": 0.05,
}


def _num(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def build_dynamic_scenario(targets: dict, title: str = "Custom agreement") -> Scenario:
    """Build a two-party scenario from the user's *own* probed targets.

    `targets` maps each dimension to {"target", "walk_away", "importance"}.
    The user is modelled as the Buyer; a counterparty (Seller) term sheet is
    derived so that a zone of possible agreement always exists. Nothing is
    hardcoded — the numbers come from what the user told their agent.
    """
    defaults = BUYER_TERM_SHEET["limits"]
    buyer_limits: dict = {}
    importances: dict[str, float] = {}

    for dim in ("price", "delivery_weeks", "warranty_months", "support_hours"):
        t = targets.get(dim, {}) if isinstance(targets, dict) else {}
        target = _num(t.get("target"), defaults[dim]["target"])
        walk = _num(t.get("walk_away"), defaults[dim]["walk_away"])
        buyer_limits[dim] = {"target": _round_dim(dim, target), "walk_away": _round_dim(dim, walk)}
        importances[dim] = max(1.0, _num(t.get("importance"), 3.0))

    pay = targets.get("payment_terms", {}) if isinstance(targets, dict) else {}
    buyer_pay_target = pay.get("target") if pay.get("target") in PAYMENT_ORDER else "net60"
    buyer_limits["payment_terms"] = {"acceptable": PAYMENT_ORDER, "target": buyer_pay_target}
    importances["payment_terms"] = max(1.0, _num(pay.get("importance"), 3.0))

    # Derive the counterparty so a deal is always reachable (ZOPA guaranteed).
    seller_limits: dict = {}
    for dim, direction in BUYER_DIRECTION.items():
        bt = buyer_limits[dim]["target"]
        bw = buyer_limits[dim]["walk_away"]
        if direction == "low":  # buyer wants low, counterparty wants high
            seller_limits[dim] = {"target": _round_dim(dim, bw), "walk_away": _round_dim(dim, bt * 0.9)}
        else:  # buyer wants high, counterparty wants low
            seller_limits[dim] = {"target": _round_dim(dim, bw), "walk_away": _round_dim(dim, bt * 1.1)}
    seller_limits["payment_terms"] = {"acceptable": PAYMENT_ORDER, "target": "net30"}

    total_imp = sum(importances.values()) or 1.0
    buyer_weights = {d: round(importances[d] / total_imp, 3) for d in importances}

    ranked = sorted(importances, key=lambda d: -importances[d])

    buyer_sheet = {
        "role": "Buyer",
        "description": f"You represent your principal in: {title}.",
        "priority_ranking": ranked,
        "priorities": _priorities_text(ranked, buyer_limits),
        "limits": buyer_limits,
        "weights": buyer_weights,
    }
    seller_sheet = {
        "role": "Seller",
        "description": f"You represent the counterparty in: {title}.",
        "priority_ranking": sorted(_COUNTERPARTY_WEIGHTS, key=lambda d: -_COUNTERPARTY_WEIGHTS[d]),
        "priorities": "Counterparty prioritises delivery time and limiting included support.",
        "limits": seller_limits,
        "weights": dict(_COUNTERPARTY_WEIGHTS),
    }
    return Scenario(
        key="custom",
        title=title,
        dimensions=DIMENSIONS,
        buyer=buyer_sheet,
        seller=seller_sheet,
        description=f"User-defined agreement: {title}.",
    )


def _round_dim(dim: str, value: float):
    if dim == "price":
        return int(round(value / 500.0) * 500)
    return max(0, int(round(value)))


def _priorities_text(ranked: list[str], limits: dict) -> str:
    parts = []
    for i, d in enumerate(ranked, 1):
        label = DIM_LABELS.get(d, d)
        tgt = limits[d].get("target")
        parts.append(f"{i}) {label} (target {tgt})")
    return ", ".join(parts)
