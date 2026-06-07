"""Critic agent — scores proposals against each party's utility function."""

from __future__ import annotations

from ..domain.scoring import party_dimension_scores, score_outcome
from ..domain.term_sheets import Scenario
from ..observability import op
from .base import Agent


class CriticAgent(Agent):
    role = "critic"

    def __init__(self, scenario: Scenario):
        super().__init__(name="critic")
        self.scenario = scenario

    @op(name="critic.evaluate", kind="agent")
    def evaluate(self, terms: dict) -> dict:
        score = score_outcome(terms, self.scenario)
        verdict = (
            "Pareto-efficient" if score["joint_surplus"] >= 130
            else "Reasonable deal" if score["joint_surplus"] >= 100
            else "Value left on table"
        )
        return {**score, "verdict": verdict}

    @op(name="critic.dimension_breakdown", kind="agent")
    def dimension_breakdown(self, terms: dict) -> dict:
        return {
            "buyer": party_dimension_scores(terms, "Buyer", self.scenario),
            "seller": party_dimension_scores(terms, "Seller", self.scenario),
        }
