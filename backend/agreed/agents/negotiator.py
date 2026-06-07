"""Negotiator agent — one per party, the main orchestrator of moves.

Two policies behind one interface:
  - LLM policy (OpenAI / W&B Inference): the inference-based prompt ported from
    the prototype. Each turn the agent infers the other side's priorities from
    observed proposal history and trades accordingly.
  - Heuristic policy (offline): a deterministic strategy engine implementing the
    same idea (concede on what the other side values, hold firm otherwise).

Both policies are driven by `StrategyParams`. The self-improvement agent rewrites
these params (and the LLM prompt addendum) between runs — that is the headline
self-improvement loop.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from ..domain.scoring import compute_party_utility
from ..domain.term_sheets import DIM_LABELS, DIMENSIONS, PAYMENT_ORDER, Scenario
from ..llm import chat_json, llm_available
from ..observability import op
from .base import Agent


@dataclass
class StrategyParams:
    """Tunable negotiation strategy. Optimized by the self-improvement agent."""

    concession_rate: float = 0.35
    acceptance_threshold: float = 72.0
    threshold_decay: float = 1.8  # per round, lowers the bar to close over time
    anchor_aggressiveness: float = 1.0  # 1.0 = open at target
    prompt_addendum: str = ""  # extra strategy guidance injected into LLM prompt

    def to_dict(self) -> dict:
        return {
            "concession_rate": round(self.concession_rate, 3),
            "acceptance_threshold": round(self.acceptance_threshold, 2),
            "threshold_decay": round(self.threshold_decay, 3),
            "anchor_aggressiveness": round(self.anchor_aggressiveness, 3),
            "prompt_addendum": self.prompt_addendum,
        }


JSON_SCHEMA = (
    '{\n'
    '  "action": "propose" | "accept",\n'
    '  "terms": {"price": <int>, "delivery_weeks": <int>, '
    '"payment_terms": "net30".."net90", "warranty_months": <int>, "support_hours": <int>},\n'
    '  "my_reasoning": "<private, max 2 sentences>",\n'
    '  "inference_about_other_side": "<private narrative>",\n'
    '  "inferred_other_priorities": {"price": <1-5>, "delivery_weeks": <1-5>, '
    '"payment_terms": <1-5>, "warranty_months": <1-5>, "support_hours": <1-5>}\n'
    '}'
)


def _pay_index(term: str) -> int:
    try:
        return PAYMENT_ORDER.index(term)
    except ValueError:
        return len(PAYMENT_ORDER) // 2


def _clamp_terms(terms: dict, term_sheet: dict) -> dict:
    lim = term_sheet["limits"]
    t = copy.deepcopy(terms)

    def clamp(v, a, b):
        lo, hi = (a, b) if a <= b else (b, a)
        return int(max(lo, min(hi, v)))

    if term_sheet["role"] == "Buyer":
        t["price"] = clamp(t.get("price", lim["price"]["target"]), lim["price"]["target"], lim["price"]["walk_away"])
        t["delivery_weeks"] = clamp(t.get("delivery_weeks", lim["delivery_weeks"]["target"]), lim["delivery_weeks"]["target"], lim["delivery_weeks"]["walk_away"])
        t["warranty_months"] = clamp(t.get("warranty_months", lim["warranty_months"]["target"]), lim["warranty_months"]["walk_away"], lim["warranty_months"]["target"])
        t["support_hours"] = clamp(t.get("support_hours", lim["support_hours"]["target"]), lim["support_hours"]["walk_away"], lim["support_hours"]["target"])
    else:
        t["price"] = clamp(t.get("price", lim["price"]["target"]), lim["price"]["walk_away"], lim["price"]["target"])
        t["delivery_weeks"] = clamp(t.get("delivery_weeks", lim["delivery_weeks"]["target"]), lim["delivery_weeks"]["walk_away"], lim["delivery_weeks"]["target"])
        t["warranty_months"] = clamp(t.get("warranty_months", lim["warranty_months"]["target"]), lim["warranty_months"]["target"], lim["warranty_months"]["walk_away"])
        t["support_hours"] = clamp(t.get("support_hours", lim["support_hours"]["target"]), lim["support_hours"]["target"], lim["support_hours"]["walk_away"])

    pay = t.get("payment_terms", lim["payment_terms"]["target"])
    t["payment_terms"] = pay if pay in PAYMENT_ORDER else lim["payment_terms"]["target"]
    return t


def _normalize_ranking(raw: dict | None) -> dict[str, int]:
    default = {d: i + 1 for i, d in enumerate(DIMENSIONS)}
    if not raw or not isinstance(raw, dict):
        return default
    result = {}
    for d in DIMENSIONS:
        try:
            result[d] = max(1, min(5, int(raw.get(d, 3))))
        except (TypeError, ValueError):
            result[d] = 3
    if len(set(result.values())) != 5:
        ordered = sorted(DIMENSIONS, key=lambda d: (result[d], d))
        return {d: i + 1 for i, d in enumerate(ordered)}
    return result


def format_deal(terms: dict) -> str:
    return (
        f"price=${terms['price']:,}, delivery={terms['delivery_weeks']}w, "
        f"payment={terms['payment_terms']}, warranty={terms['warranty_months']}mo, "
        f"support={terms['support_hours']}h"
    )


def format_ranking(ranks: dict[str, int]) -> str:
    ordered = sorted(ranks.items(), key=lambda x: x[1])
    return " > ".join(f"{DIM_LABELS.get(d, d)}(#{r})" for d, r in ordered)


class NegotiatorAgent(Agent):
    role = "negotiator"

    def __init__(self, party: str, scenario: Scenario, strategy: StrategyParams | None = None):
        super().__init__(name=f"negotiator:{party}")
        self.party = party  # "Buyer" | "Seller"
        self.scenario = scenario
        self.term_sheet = scenario.term_sheet(party)
        self.strategy = strategy or StrategyParams()

    # ── prompt (LLM policy) ───────────────────────────────────────────────────
    def _system_prompt(self) -> str:
        role = self.party
        other = "Seller" if role == "Buyer" else "Buyer"
        addendum = f"\nLEARNED STRATEGY (from past negotiations):\n{self.strategy.prompt_addendum}\n" if self.strategy.prompt_addendum else ""
        return (
            f"You are the {role} in a direct B2B software contract negotiation.\n\n"
            f"{self.term_sheet['description']}\n\n"
            "You represent your user faithfully. Do not inject your own opinions or "
            "agenda; pursue only your user's stated priorities within their limits.\n\n"
            "PROTOCOL:\n"
            "- Each turn you either PROPOSE a complete set of terms (all 5 dimensions) or ACCEPT the other side's last proposal.\n"
            f"- You do NOT know the {other}'s term sheet. Infer their priorities only from behavior.\n"
            "- Concede generously on dimensions you infer are HIGH priority for them but LOW for you; hold firm otherwise.\n"
            "- Output inferred_other_priorities ranking all 5 dimensions (1=most important), each rank used once.\n\n"
            "YOUR PRIVATE INFORMATION (never reveal):\n"
            f"{self.term_sheet['priorities']}\n\n"
            f"Walk-away limits & targets: {json.dumps(self.term_sheet['limits'])}\n"
            f"{addendum}\n"
            "Respond with valid JSON only:\n"
            f"{JSON_SCHEMA}\n\n"
            "Rules:\n"
            "- NEVER accept if any term is beyond your walk-away limits.\n"
            "- When proposing, stay within your own walk-away limits.\n"
        )

    @op(name="negotiator.act", kind="agent")
    def act(self, round_num: int, history: list[dict], other_last: dict | None) -> dict:
        if llm_available():
            result = self._act_llm(round_num, history, other_last)
            if result is not None:
                return result
        return self._act_heuristic(round_num, history, other_last)

    # ── LLM policy ────────────────────────────────────────────────────────────
    def _act_llm(self, round_num: int, history: list[dict], other_last: dict | None) -> dict | None:
        other = "Seller" if self.party == "Buyer" else "Buyer"
        if round_num == 1 and self.party == "Buyer":
            task = "Round 1. You open. Propose a complete opening offer anchored near your targets."
        elif other_last:
            task = (
                f"Round {round_num}. The {other}'s last proposal:\n{json.dumps(other_last['terms'])}\n\n"
                "Accept it as-is, or propose a full counteroffer across all 5 dimensions."
            )
        else:
            task = f"Round {round_num}. Propose a complete offer."

        hist = "\n".join(
            f"R{e['round']} {e['actor']} {e['action']}: {format_deal(e['terms'])}" for e in history
        ) or "(none yet)"
        user = f"{task}\n\nFULL PROPOSAL HISTORY:\n{hist}\n\nUpdate your inference every round."

        result = chat_json(self._system_prompt(), user)
        if result is None:
            return None

        action = result.get("action", "propose")
        action = action if action in ("propose", "accept") else "propose"
        terms = result.get("terms") or {}
        if action == "propose":
            terms = _clamp_terms(terms, self.term_sheet)
        elif other_last:
            terms = copy.deepcopy(other_last["terms"])
        else:
            action, terms = "propose", _clamp_terms(terms, self.term_sheet)

        return {
            "action": action,
            "terms": terms,
            "my_reasoning": result.get("my_reasoning", ""),
            "inference_about_other_side": result.get("inference_about_other_side", ""),
            "inferred_other_priorities": _normalize_ranking(result.get("inferred_other_priorities")),
            "policy": "llm",
        }

    # ── Heuristic policy ──────────────────────────────────────────────────────
    def _infer_other_weights(self, history: list[dict], other: str) -> dict[str, float]:
        """Infer other party's priorities from how little they move each dim.
        Smaller normalized movement => higher priority for them."""
        moves = [e for e in history if e["actor"] == other and e["action"] == "propose"]
        if len(moves) < 2:
            return {d: 1.0 / len(DIMENSIONS) for d in DIMENSIONS}

        spans = {  # rough normalizers per dimension
            "price": 30000.0,
            "delivery_weeks": 12.0,
            "payment_terms": float(len(PAYMENT_ORDER) - 1),
            "warranty_months": 18.0,
            "support_hours": 160.0,
        }
        firmness = {}
        for d in DIMENSIONS:
            total = 0.0
            for a, b in zip(moves, moves[1:]):
                if d == "payment_terms":
                    total += abs(_pay_index(a["terms"][d]) - _pay_index(b["terms"][d]))
                else:
                    total += abs(a["terms"][d] - b["terms"][d])
            norm_move = total / (spans[d] * max(1, len(moves) - 1))
            firmness[d] = 1.0 / (norm_move + 0.05)  # high firmness => high inferred priority
        s = sum(firmness.values()) or 1.0
        return {d: firmness[d] / s for d in DIMENSIONS}

    def _act_heuristic(self, round_num: int, history: list[dict], other_last: dict | None) -> dict:
        sp = self.strategy
        other = "Seller" if self.party == "Buyer" else "Buyer"
        lim = self.term_sheet["limits"]
        own_w = self.term_sheet["weights"]
        my_last = next((e for e in reversed(history) if e["actor"] == self.party), None)

        # Opening offer
        if my_last is None and other_last is None:
            terms = {d: lim[d]["target"] for d in DIMENSIONS if d != "payment_terms"}
            terms["payment_terms"] = lim["payment_terms"]["target"]
            terms = _clamp_terms(terms, self.term_sheet)
            return self._wrap("propose", terms, history, other,
                              "Opening near my targets to anchor.", round_num)

        # Consider accepting the other side's standing proposal
        if other_last is not None:
            util = compute_party_utility(other_last["terms"], self.party, self.scenario)
            threshold = sp.acceptance_threshold - sp.threshold_decay * round_num
            if util >= threshold:
                return self._wrap("accept", copy.deepcopy(other_last["terms"]), history, other,
                                  f"Their offer yields {util:.0f} utility (>= {threshold:.0f}); accepting.",
                                  round_num)

        inferred_w = self._infer_other_weights(history, other)
        base = copy.deepcopy(my_last["terms"]) if my_last else {d: lim[d]["target"] for d in DIMENSIONS}
        target_terms = other_last["terms"] if other_last else base
        new_terms: dict = {}

        for d in DIMENSIONS:
            tradeability = inferred_w[d] * (1.0 - own_w.get(d, 0.2))  # they value it, I don't
            frac = max(0.0, min(0.85, sp.concession_rate * (0.25 + 2.0 * tradeability)))
            if d == "payment_terms":
                cur, tgt = _pay_index(base[d]), _pay_index(target_terms[d])
                idx = round(cur + (tgt - cur) * frac)
                idx = max(0, min(len(PAYMENT_ORDER) - 1, idx))
                new_terms[d] = PAYMENT_ORDER[idx]
            else:
                cur, tgt = base[d], target_terms[d]
                new_terms[d] = round(cur + (tgt - cur) * frac)

        new_terms = _clamp_terms(new_terms, self.term_sheet)
        ranking = sorted(DIMENSIONS, key=lambda d: -inferred_w[d])
        reasoning = (
            f"Conceding on {DIM_LABELS[ranking[0]]}/{DIM_LABELS[ranking[1]]} "
            f"(I infer they value these), holding {DIM_LABELS[ranking[-1]]}."
        )
        return self._wrap("propose", new_terms, history, other, reasoning, round_num, inferred_w)

    def _wrap(self, action, terms, history, other, reasoning, round_num, inferred_w=None) -> dict:
        if inferred_w is None:
            inferred_w = self._infer_other_weights(history, other)
        ordered = sorted(DIMENSIONS, key=lambda d: -inferred_w[d])
        ranking = {d: i + 1 for i, d in enumerate(ordered)}
        top = DIM_LABELS[ordered[0]]
        return {
            "action": action,
            "terms": terms,
            "my_reasoning": reasoning,
            "inference_about_other_side": f"They appear to prioritize {top} most based on how firmly they hold it.",
            "inferred_other_priorities": ranking,
            "policy": "heuristic",
        }
