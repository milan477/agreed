"""Representation agent — learns about the user (step 1 onboarding interview) and
prepares the negotiation brief (step 2.5).

The onboarding interview asks targeted questions to learn intent, priorities,
constraints, and style, then produces a written user profile + intent summary the
user approves. Works over any channel (web/text/voice); the channel just supplies
answers. Uses the LLM when available, else a structured template.
"""

from __future__ import annotations

from ..domain.term_sheets import DIM_LABELS, Scenario
from ..llm import chat_text
from ..observability import op
from .base import Agent
from .researcher import ResearcherAgent

ONBOARDING_QUESTIONS = [
    "What are you trying to achieve with this agreement, in one sentence?",
    "Which outcome matters most to you, and what would make you walk away?",
    "Are there any hard constraints (budget, timeline, legal) we must respect?",
    "How aggressive vs. relationship-preserving should your agent be?",
    "Is there anything about the other party or context we should know?",
]


class RepresentationAgent(Agent):
    role = "representation"

    def __init__(self, scenario: Scenario):
        super().__init__(name="representation")
        self.scenario = scenario
        self.researcher = ResearcherAgent()

    @op(name="representation.questions", kind="agent")
    def questions(self) -> list[str]:
        return list(ONBOARDING_QUESTIONS)

    @op(name="representation.build_profile", kind="agent")
    def build_profile(self, party: str, purpose: str, answers: dict[str, str]) -> dict:
        """Turn interview answers into a structured user profile + intent summary."""
        term_sheet = self.scenario.term_sheet(party)
        priorities = term_sheet["priority_ranking"]
        summary = self._intent_summary(party, purpose, answers, priorities)
        return {
            "party": party,
            "purpose": purpose,
            "priorities": [DIM_LABELS.get(p, p) for p in priorities],
            "constraints": answers.get("constraints", ""),
            "style": answers.get("style", "balanced"),
            "intent_summary": summary,
            "raw_answers": answers,
            "approved": False,  # user must approve before continuing
        }

    def _intent_summary(self, party, purpose, answers, priorities) -> str:
        text = chat_text(
            system=(
                "You write a concise, neutral one-paragraph intent summary for a "
                "negotiation. Represent the user faithfully; inject no opinions."
            ),
            user=(
                f"Party: {party}\nPurpose: {purpose}\nAnswers: {answers}\n"
                f"Inferred priority order: {priorities}\n"
                "Write the intent summary (3-4 sentences)."
            ),
        )
        if text:
            return text.strip()
        top = ", ".join(DIM_LABELS.get(p, p) for p in priorities[:3])
        return (
            f"As the {party.lower()}, the user's goal is to {purpose.lower()}. "
            f"Their priorities, in order, are {top}. "
            f"Style: {answers.get('style', 'balanced')}. "
            "The agent will pursue these priorities within the user's stated limits "
            "and pause for confirmation before any out-of-scope concession."
        )

    @op(name="representation.build_brief", kind="agent")
    def build_brief(self, party: str, profile: dict, *, self_improved: bool = False) -> dict:
        """Step 2.5: research + ranked priorities + walk-aways + opening + strategy."""
        term_sheet = self.scenario.term_sheet(party)
        research = self.researcher.research(f"{self.scenario.title} {party} negotiation benchmarks")
        return {
            "party": party,
            "ranked_priorities": [DIM_LABELS.get(p, p) for p in term_sheet["priority_ranking"]],
            "walk_away_points": term_sheet["limits"],
            "opening_position": {d: term_sheet["limits"][d]["target"] for d in term_sheet["limits"]},
            "research_findings": research["findings"],
            "strategy": (
                "Open near targets; infer the other side's priorities from their moves; "
                "trade away what they value and you don't; hold firm on your top priorities."
            ),
            "self_improved": self_improved,
            "approved": False,
        }
