"""Core negotiation loop.

Pure, dependency-light turn-taking between two negotiator agents, optionally
supervised by a moderator. This is the substrate the LangGraph orchestrator wraps
and that the self-improvement agent uses for fast self-play rollouts.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

from ..agents.critic import CriticAgent
from ..agents.moderator import ModeratorAgent
from ..agents.negotiator import NegotiatorAgent, StrategyParams, format_deal
from ..domain.frameworks import Framework, get_framework
from ..domain.scoring import compute_party_utility, score_outcome
from ..domain.term_sheets import Scenario, get_scenario
from ..observability import op, record_event, trace_context


@dataclass
class NegotiationResult:
    outcome: str  # "deal" | "no_deal"
    deal_terms: dict | None
    rounds: int
    transcript: list[dict]
    accepted_by: str | None
    forced_at_max_rounds: bool
    score: dict | None
    settlement: dict | None
    trace_id: str
    framework: str

    def to_dict(self) -> dict:
        return asdict(self)


@op(name="engine.run_negotiation", kind="graph")
def run_negotiation(
    scenario: Scenario | None = None,
    *,
    framework: Framework | str | None = None,
    buyer_strategy: StrategyParams | None = None,
    seller_strategy: StrategyParams | None = None,
    max_rounds: int = 16,
    use_moderator: bool = True,
    trace_id: str | None = None,
    verbose: bool = False,
) -> NegotiationResult:
    scenario = scenario or get_scenario()
    fw = framework if isinstance(framework, Framework) else get_framework(framework)

    buyer = NegotiatorAgent("Buyer", scenario, buyer_strategy)
    seller = NegotiatorAgent("Seller", scenario, seller_strategy)
    moderator = ModeratorAgent(scenario, fw, max_rounds=max_rounds) if use_moderator else None

    with trace_context(trace_id) as tid:
        record_event("negotiation_start", kind="graph", framework=fw.key, max_rounds=max_rounds)
        transcript: list[dict] = []
        last = {"Buyer": None, "Seller": None}
        outcome, deal_terms, accepted_by = "no_deal", None, None
        forced = False
        round_num = 0

        for round_num in range(1, max_rounds + 1):
            actor = "Buyer" if round_num % 2 == 1 else "Seller"
            agent = buyer if actor == "Buyer" else seller
            other = "Seller" if actor == "Buyer" else "Buyer"
            other_last = last[other]

            resp = agent.act(round_num, transcript, other_last)

            # Moderator enforces framework hard-constraints on proposals.
            mod_note = None
            if moderator and resp["action"] == "propose":
                check = moderator.check_proposal(resp["terms"])
                if not check["feasible"]:
                    mod_note = f"Moderator: {check['reason']}"

            entry = {
                "round": round_num,
                "actor": actor,
                "action": resp["action"],
                "terms": copy.deepcopy(resp["terms"]),
                "my_reasoning": resp["my_reasoning"],
                "inference_about_other_side": resp["inference_about_other_side"],
                "inferred_other_priorities": resp["inferred_other_priorities"],
                "policy": resp.get("policy", "llm"),
                "moderator_note": mod_note,
                "buyer_utility": round(compute_party_utility(resp["terms"], "Buyer", scenario), 1),
                "seller_utility": round(compute_party_utility(resp["terms"], "Seller", scenario), 1),
            }
            transcript.append(entry)
            last[actor] = entry

            if verbose:
                print(f"R{round_num:2} [{actor:6}] {resp['action']}: {format_deal(resp['terms'])}")
                print(f"        {resp['my_reasoning']}")

            if resp["action"] == "accept":
                if other_last is None:
                    continue  # nothing to accept yet
                outcome = "deal"
                deal_terms = copy.deepcopy(other_last["terms"])
                accepted_by = actor
                break

            if round_num == max_rounds:
                outcome = "deal"
                deal_terms = copy.deepcopy(resp["terms"])
                forced = True

        score = score_outcome(deal_terms, scenario) if deal_terms else None
        settlement = None
        if moderator and deal_terms is not None:
            settlement = moderator.propose_settlement(transcript, agreed_terms=deal_terms)

        record_event(
            "negotiation_end",
            kind="graph",
            outcome=outcome,
            rounds=round_num,
            joint_surplus=(score or {}).get("joint_surplus"),
        )

        return NegotiationResult(
            outcome=outcome,
            deal_terms=deal_terms,
            rounds=round_num,
            transcript=transcript,
            accepted_by=accepted_by,
            forced_at_max_rounds=forced,
            score=score,
            settlement=settlement,
            trace_id=tid,
            framework=fw.key,
        )
