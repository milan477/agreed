"""Conversational negotiation between two live agents.

Unlike the structured term-sheet loop, this drives an *actual conversation*: the
user's agent and a generated counterparty agent exchange messages and converge to
an agreement. Two interaction modes (both parties must agree on one up front):

  - "structured": each turn carries a concrete proposal across the negotiable
    dimensions, narrated in natural language. Utility/Pareto scoring applies.
  - "textual": a purely free-form exchange of positions, concessions and a final
    agreement statement. Used for participations/deliberations and for parties who
    prefer to talk it out.

The counterparty is a *mock* party: a second agent with its own (generated)
targets, so the demo never needs a second human. Everything is Weave-traced and
runs offline via deterministic fallbacks when no LLM is configured.
"""

from __future__ import annotations

import copy

from ..agents.negotiator import NegotiatorAgent, StrategyParams, format_deal
from ..domain.frameworks import get_framework
from ..domain.scoring import compute_party_utility, score_outcome
from ..domain.term_sheets import DIM_LABELS, Scenario, get_scenario
from ..llm import chat_text, llm_available
from ..observability import op, record_event, trace_context
from ..sandbox.runner import provision_sandboxes


class ConversationalNegotiation:
    def __init__(
        self,
        *,
        mode: str = "structured",
        scenario: Scenario | None = None,
        topic: str = "the agreement",
        user_label: str = "Your agent",
        counter_label: str = "Counterparty agent",
        user_voice: str = "",
        viewpoints: list[dict] | None = None,
        max_rounds: int = 10,
        framework: str = "pareto",
    ):
        self.mode = mode if mode in ("structured", "textual") else "structured"
        self.scenario = scenario or get_scenario()
        self.topic = topic
        self.user_label = user_label
        self.counter_label = counter_label
        self.user_voice = user_voice
        self.viewpoints = viewpoints or []
        self.max_rounds = max_rounds
        self.framework = get_framework(framework)

    @op(name="conversation.run", kind="graph")
    def run(self, *, trace_id: str | None = None) -> dict:
        with trace_context(trace_id) as tid:
            provision_sandboxes([f"agent:{self.user_label}", f"agent:{self.counter_label}"])
            record_event("conversation_start", kind="graph", mode=self.mode, topic=self.topic)
            if self.mode == "structured":
                result = self._run_structured()
            else:
                result = self._run_textual()
            result["trace_id"] = tid
            result["mode"] = self.mode
            record_event("conversation_end", kind="graph", outcome=result["outcome"], rounds=result["rounds"])
            return result

    # ── structured: real proposals, narrated as a conversation ────────────────
    def _run_structured(self) -> dict:
        buyer = NegotiatorAgent("Buyer", self.scenario)
        seller = NegotiatorAgent("Seller", self.scenario, StrategyParams(acceptance_threshold=68.0))
        transcript: list[dict] = []
        messages: list[dict] = []
        last_buyer = last_seller = None
        outcome, deal_terms, accepted_by = "no_deal", None, None
        rnd = 1
        while rnd <= self.max_rounds:
            actor = "Buyer" if rnd % 2 == 1 else "Seller"
            agent = buyer if actor == "Buyer" else seller
            other_last = last_seller if actor == "Buyer" else last_buyer
            resp = agent.act(rnd, transcript, other_last)
            entry = {
                "round": rnd,
                "actor": actor,
                "action": resp["action"],
                "terms": copy.deepcopy(resp["terms"]),
                "my_reasoning": resp["my_reasoning"],
                "buyer_utility": round(compute_party_utility(resp["terms"], "Buyer", self.scenario), 1),
                "seller_utility": round(compute_party_utility(resp["terms"], "Seller", self.scenario), 1),
                "moderator_note": None,
            }
            transcript.append(entry)
            speaker = self.user_label if actor == "Buyer" else self.counter_label
            text = self._narrate_structured(actor, resp, other_last)
            messages.append({
                "round": rnd,
                "speaker": speaker,
                "side": "you" if actor == "Buyer" else "them",
                "action": resp["action"],
                "text": text,
                "terms": copy.deepcopy(resp["terms"]),
            })
            if actor == "Buyer":
                last_buyer = entry
            else:
                last_seller = entry
            if resp["action"] == "accept" and other_last is not None:
                outcome, deal_terms, accepted_by = "deal", copy.deepcopy(other_last["terms"]), speaker
                break
            if rnd >= self.max_rounds:
                # Forced close: settle on whichever standing offer is fairer
                # (higher worst-off utility) instead of the last speaker's terms.
                candidates = [e["terms"] for e in (last_buyer, last_seller, entry) if e]
                deal_terms = max(
                    candidates,
                    key=lambda t: min(
                        compute_party_utility(t, "Buyer", self.scenario),
                        compute_party_utility(t, "Seller", self.scenario),
                    ),
                )
                outcome, deal_terms = "deal", copy.deepcopy(deal_terms)
                break
            rnd += 1

        score = score_outcome(deal_terms, self.scenario) if deal_terms else None
        summary = self._summary_structured(outcome, deal_terms, score)
        return {
            "outcome": outcome,
            "rounds": rnd,
            "messages": messages,
            "transcript": transcript,
            "agreement_terms": deal_terms,
            "agreement_text": format_deal(deal_terms) if deal_terms else None,
            "accepted_by": accepted_by,
            "score": score,
            "summary": summary,
        }

    def _narrate_structured(self, actor: str, resp: dict, other_last: dict | None) -> str:
        terms = resp["terms"]
        deal = (
            f"${terms['price']:,}, {terms['delivery_weeks']}-week delivery, {terms['payment_terms']}, "
            f"{terms['warranty_months']}mo warranty, {terms['support_hours']}h support"
        )
        if llm_available():
            voice = f"Match this person's voice/tone: \"{self.user_voice}\".\n" if (actor == "Buyer" and self.user_voice) else ""
            sys = (
                "You are an agent negotiating on behalf of a principal. Write ONE short, natural "
                "chat message (1-2 sentences) that states or responds to an offer. Sound human, not robotic. "
                + voice
            )
            usr = (
                f"Topic: {self.topic}. You are the {'buyer-side' if actor == 'Buyer' else 'seller-side'} agent.\n"
                f"Your move: {resp['action']} -> {deal}.\n"
                f"Private reasoning: {resp.get('my_reasoning', '')}.\n"
                + (f"Their last offer: {format_deal(other_last['terms'])}.\n" if other_last else "")
                + "Write the message:"
            )
            text = chat_text(sys, usr, max_tokens=120, temperature=0.7)
            if text:
                return text.strip()
        if resp["action"] == "accept":
            return f"That works for me — let's lock it in: {deal}. Deal."
        opener = "Here's where I'd like to land" if other_last is None else "I can move a bit — how about"
        return f"{opener}: {deal}. {resp.get('my_reasoning', '')}".strip()

    def _summary_structured(self, outcome, deal_terms, score) -> str:
        if outcome != "deal" or not deal_terms:
            return "No agreement was reached within the round limit."
        s = f"Agreement reached: {format_deal(deal_terms)}."
        if score:
            s += f" Your value {score['buyer_score']}/100."
        return s

    # ── textual: free-form negotiation / deliberation ─────────────────────────
    def _run_textual(self) -> dict:
        positions = self._opening_positions()
        messages: list[dict] = []
        rounds = min(self.max_rounds, 6)
        history: list[tuple[str, str]] = []

        for rnd in range(1, rounds + 1):
            for actor in ("Buyer", "Seller"):
                speaker = self.user_label if actor == "Buyer" else self.counter_label
                phase = "open" if rnd == 1 else ("close" if rnd == rounds else "trade")
                text = self._textual_turn(actor, phase, positions, history)
                history.append((speaker, text))
                messages.append({
                    "round": rnd,
                    "speaker": speaker,
                    "side": "you" if actor == "Buyer" else "them",
                    "action": "message",
                    "text": text,
                })

        agreement_text = self._textual_agreement(history)
        return {
            "outcome": "deal",
            "rounds": rounds,
            "messages": messages,
            "transcript": [],
            "agreement_terms": None,
            "agreement_text": agreement_text,
            "accepted_by": None,
            "score": None,
            "summary": agreement_text,
        }

    def _opening_positions(self) -> list[str]:
        if self.viewpoints:
            return [
                f"{v.get('topic', 'point')}: {v.get('stance', '')}".strip(": ").strip()
                for v in self.viewpoints
                if v.get("stance") or v.get("topic")
            ]
        return [self.topic]

    def _textual_turn(self, actor: str, phase: str, positions: list[str], history) -> str:
        if llm_available():
            voice = f"Match this person's voice/tone: \"{self.user_voice}\".\n" if (actor == "Buyer" and self.user_voice) else ""
            role = "the user's side" if actor == "Buyer" else "the counterparty"
            convo = "\n".join(f"{s}: {t}" for s, t in history[-6:]) or "(start of conversation)"
            sys = (
                "You are negotiating/deliberating on behalf of a principal in a live chat. "
                "Write ONE natural message (1-3 sentences). Make real progress: state a position, "
                "acknowledge the other side, propose a concession or common ground. " + voice
            )
            usr = (
                f"Topic: {self.topic}.\nYou represent {role}.\n"
                f"Your principal's positions/priorities: {positions}.\n"
                f"Conversation so far:\n{convo}\n"
                f"This is the {phase} phase. Write your next message:"
            )
            text = chat_text(sys, usr, max_tokens=150, temperature=0.7)
            if text:
                return text.strip()
        return self._textual_fallback(actor, phase, positions)

    def _textual_fallback(self, actor: str, phase: str, positions: list[str]) -> str:
        first = positions[0] if positions else self.topic
        if actor == "Buyer":
            if phase == "open":
                return f"Thanks for making time. My priority here is {first}. I'd like us to find something that works for both of us."
            if phase == "close":
                return "That's fair — I think we've found common ground. I'm good to move forward on this."
            extra = positions[1] if len(positions) > 1 else "the timeline"
            return f"I hear you. I can be flexible on {extra} if we can protect {first}."
        if phase == "open":
            return "Appreciated. From our side, we need this to be workable operationally, but I'm optimistic we can align."
        if phase == "close":
            return "Agreed. Let's put it in writing and proceed on those terms."
        return f"That's reasonable. We can accommodate {first} provided we keep the scope realistic."

    def _textual_agreement(self, history) -> str:
        if llm_available():
            convo = "\n".join(f"{s}: {t}" for s, t in history)
            sys = "Summarise the agreement reached in this conversation as 1-2 neutral sentences."
            text = chat_text(sys, f"Topic: {self.topic}.\nConversation:\n{convo}\n\nAgreement:", max_tokens=120)
            if text:
                return text.strip()
        pts = self._opening_positions()
        joined = "; ".join(pts[:3])
        return f"Both sides agreed to proceed on {self.topic}, aligning on: {joined}."
