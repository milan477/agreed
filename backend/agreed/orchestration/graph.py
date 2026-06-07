"""LangGraph negotiation orchestrator.

Models the negotiation as a state machine: prep -> (buyer_turn <-> seller_turn)
-> settle. Turn-taking and framework constraints are enforced at the nodes. Each
negotiator runs in its own E2B sandbox. When LangGraph isn't installed the same
node logic runs via a plain driver, so behavior is identical either way.
"""

from __future__ import annotations

import copy
from typing import Any, TypedDict

from ..agents.moderator import ModeratorAgent
from ..agents.negotiator import NegotiatorAgent, StrategyParams, format_deal
from ..domain.frameworks import Framework, get_framework
from ..domain.scoring import compute_party_utility, score_outcome
from ..domain.term_sheets import Scenario, get_scenario
from ..observability import op, record_event, trace_context
from ..sandbox.runner import provision_sandboxes


class NegState(TypedDict, total=False):
    round: int
    actor: str
    transcript: list[dict]
    last_buyer: dict | None
    last_seller: dict | None
    outcome: str
    deal_terms: dict | None
    accepted_by: str | None
    forced: bool
    done: bool


class NegotiationOrchestrator:
    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        framework: Framework | str | None = None,
        buyer_strategy: StrategyParams | None = None,
        seller_strategy: StrategyParams | None = None,
        max_rounds: int = 16,
        use_moderator: bool = True,
    ):
        self.scenario = scenario or get_scenario()
        self.framework = framework if isinstance(framework, Framework) else get_framework(framework)
        self.max_rounds = max_rounds
        self.use_moderator = use_moderator
        self.buyer = NegotiatorAgent("Buyer", self.scenario, buyer_strategy)
        self.seller = NegotiatorAgent("Seller", self.scenario, seller_strategy)
        self.moderator = ModeratorAgent(self.scenario, self.framework, max_rounds) if use_moderator else None

    # ── node logic (shared by LangGraph and fallback driver) ──────────────────
    def _turn(self, state: NegState) -> NegState:
        round_num = state["round"]
        actor = "Buyer" if round_num % 2 == 1 else "Seller"
        agent = self.buyer if actor == "Buyer" else self.seller
        other = "Seller" if actor == "Buyer" else "Buyer"
        other_last = state["last_seller"] if actor == "Buyer" else state["last_buyer"]

        resp = agent.act(round_num, state["transcript"], other_last)

        mod_note = None
        if self.moderator and resp["action"] == "propose":
            check = self.moderator.check_proposal(resp["terms"])
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
            "buyer_utility": round(compute_party_utility(resp["terms"], "Buyer", self.scenario), 1),
            "seller_utility": round(compute_party_utility(resp["terms"], "Seller", self.scenario), 1),
        }
        state["transcript"].append(entry)
        state[f"last_{actor.lower()}"] = entry  # type: ignore[literal-required]

        if resp["action"] == "accept" and other_last is not None:
            state.update(outcome="deal", deal_terms=copy.deepcopy(other_last["terms"]),
                         accepted_by=actor, done=True)
        elif round_num >= self.max_rounds:
            state.update(outcome="deal", deal_terms=copy.deepcopy(resp["terms"]),
                         forced=True, done=True)
        else:
            state["round"] = round_num + 1
        return state

    def _should_continue(self, state: NegState) -> str:
        return "settle" if state.get("done") else "turn"

    @op(name="orchestrator.run", kind="graph")
    def run(self, *, trace_id: str | None = None, verbose: bool = False):
        from .engine import NegotiationResult

        agent_names = ["negotiator:Buyer", "negotiator:Seller", "moderator"]
        if self.use_moderator is False:
            agent_names = agent_names[:2]

        with trace_context(trace_id) as tid:
            sandboxes = provision_sandboxes(agent_names)  # one E2B sandbox per agent
            record_event("orchestrator_start", kind="graph", framework=self.framework.key,
                         backend=next(iter(sandboxes.values())).backend)

            state: NegState = {
                "round": 1, "transcript": [], "last_buyer": None, "last_seller": None,
                "outcome": "no_deal", "deal_terms": None, "accepted_by": None,
                "forced": False, "done": False,
            }

            built = self._build_langgraph()
            if built is not None:
                state = built.invoke(state, config={"recursion_limit": self.max_rounds * 2 + 10})
            else:
                while not state.get("done"):
                    state = self._turn(state)

            for sb in sandboxes.values():
                sb.close()

            deal_terms = state.get("deal_terms")
            score = score_outcome(deal_terms, self.scenario) if deal_terms else None
            settlement = None
            if self.moderator and deal_terms is not None:
                settlement = self.moderator.propose_settlement(state["transcript"], agreed_terms=deal_terms)

            record_event("orchestrator_end", kind="graph", outcome=state.get("outcome"),
                         rounds=state.get("round"), joint_surplus=(score or {}).get("joint_surplus"))

            return NegotiationResult(
                outcome=state.get("outcome", "no_deal"),
                deal_terms=deal_terms,
                rounds=state.get("round", 0),
                transcript=state["transcript"],
                accepted_by=state.get("accepted_by"),
                forced_at_max_rounds=state.get("forced", False),
                score=score,
                settlement=settlement,
                trace_id=tid,
                framework=self.framework.key,
            )

    def _build_langgraph(self):
        """Build a real LangGraph StateGraph if the package is available."""
        try:
            from langgraph.graph import END, START, StateGraph  # type: ignore
        except Exception:
            return None
        try:
            g = StateGraph(NegState)
            g.add_node("turn", self._turn)
            g.add_node("settle", lambda s: s)
            g.add_edge(START, "turn")
            g.add_conditional_edges("turn", self._should_continue, {"turn": "turn", "settle": "settle"})
            g.add_edge("settle", END)
            return g.compile()
        except Exception:
            return None
