"""Connectors — how the agent learns about the user automatically.

Each connector models an MCP-style data source (mailbox, Notion, calendar,
contacts). When the user links one, the connector returns *learned facts* plus
profile enrichments (traits, tone, constraints, suggested goals and likely
counterparties). The agent reacts to these in a personal way.

Real OAuth / MCP wiring is intentionally pluggable: swap a connector's `fetch`
for a live MCP call and the rest of the platform is unchanged. The bundled
connectors return realistic, varied sample data so the experience is dynamic and
works fully offline for the demo.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from ..observability import op


@dataclass
class LearnResult:
    facts: list[dict] = field(default_factory=list)        # {summary, detail}
    traits: list[str] = field(default_factory=list)        # personality / style cues
    constraints: list[str] = field(default_factory=list)   # hard limits picked up
    suggested_goals: list[dict] = field(default_factory=list)  # {title, kind, other_party_label}
    counterparties: list[str] = field(default_factory=list)
    tone: str = ""                                          # voice cue
    agent_line: str = ""                                    # what the agent says back

    def to_dict(self) -> dict:
        return {
            "facts": self.facts,
            "traits": self.traits,
            "constraints": self.constraints,
            "suggested_goals": self.suggested_goals,
            "counterparties": self.counterparties,
            "tone": self.tone,
            "agent_line": self.agent_line,
        }


@dataclass
class Connector:
    id: str
    name: str
    kind: str       # email | notion | calendar | contacts
    icon: str       # short glyph used by the UI
    blurb: str
    fetch: Callable[[], LearnResult]


def _gmail() -> LearnResult:
    threads = random.sample(
        [
            ("Lease renewal — Maple St", "Landlord proposed +9% rent; you pushed back twice this week.",
             {"title": "Renew the Maple St lease", "kind": "negotiation", "other_party_label": "Landlord (Maple St)"}, "Landlord (Maple St)"),
            ("Re: SaaS renewal quote", "Vendor's annual quote is up 22%; thread shows you want a multi-year discount.",
             {"title": "Renegotiate the SaaS renewal", "kind": "negotiation", "other_party_label": "Vendor"}, "Account Manager"),
            ("Freelance contract — scope", "Client keeps expanding scope without adjusting the fee.",
             {"title": "Fix the freelance contract scope/fee", "kind": "negotiation", "other_party_label": "Client"}, "Client"),
            ("HOA — parking proposal", "Neighbors organising on a shared-parking rule change.",
             {"title": "Weigh in on the HOA parking rule", "kind": "participation", "other_party_label": "HOA board"}, "HOA board"),
        ],
        k=2,
    )
    facts = [{"summary": s, "detail": d} for s, d, _, _ in threads]
    goals = [g for _, _, g, _ in threads]
    parties = [p for _, _, _, p in threads]
    return LearnResult(
        facts=facts,
        traits=["follows up persistently", "cost-conscious"],
        constraints=["dislikes long lock-ins"],
        suggested_goals=goals,
        counterparties=parties,
        tone="direct, no-nonsense",
        agent_line=(
            f"Skimmed your inbox — the \"{threads[0][0]}\" thread stands out. "
            "Want me to take that one and push for a better deal?"
        ),
    )


def _notion() -> LearnResult:
    notes = random.sample(
        [
            ("Budget tracker", "You cap discretionary spend at ~$8k/quarter."),
            ("Vendor shortlist", "You weigh reliability over price — burned once by a cheap supplier."),
            ("Q3 goals doc", "Priority: lock predictable costs, avoid surprise renewals."),
            ("Move-out checklist", "Hard deadline: out by end of month."),
        ],
        k=2,
    )
    return LearnResult(
        facts=[{"summary": s, "detail": d} for s, d in notes],
        traits=["plans ahead", "values reliability"],
        constraints=["budget ~$8k/quarter", "values reliability over lowest price"],
        tone="organised, detail-oriented",
        agent_line="Read your Notion — I picked up your budget ceiling and that you'd trade a bit of price for reliability. I'll keep both in mind.",
    )


def _calendar() -> LearnResult:
    events = random.sample(
        [
            ("Call w/ landlord — Thu 4pm", "A live negotiation touchpoint is already on your calendar."),
            ("Vendor QBR — next Tue", "Renewal decision likely comes up here."),
            ("Council meeting — Mon 6pm", "Public comment window on the rezoning item."),
            ("Move-out walkthrough", "Two weeks out — time pressure is real."),
        ],
        k=2,
    )
    return LearnResult(
        facts=[{"summary": s, "detail": d} for s, d in events],
        constraints=["time-sensitive — decision needed within ~2 weeks"],
        tone="busy, wants things handled",
        agent_line="Your calendar shows a deadline coming up fast — I'll move quickly so you're ready before it lands.",
    )


def _contacts() -> LearnResult:
    people = random.sample(
        ["Alex Rivera", "Jordan Kim", "Sam Patel", "Taylor Brooks", "Morgan Lee"],
        k=3,
    )
    return LearnResult(
        facts=[{"summary": f"Frequent contact: {p}", "detail": "You message them often — likely a counterparty or ally."} for p in people],
        counterparties=people,
        agent_line=f"Pulled in your contacts — I can reach {people[0]} or {people[1]} by text the moment we need to.",
    )


REGISTRY: dict[str, Connector] = {
    "gmail": Connector("gmail", "Mailbox", "email", "✉", "Scan recent threads for live negotiations and context.", _gmail),
    "notion": Connector("notion", "Notion", "notion", "◆", "Learn your priorities, budgets and constraints from your notes.", _notion),
    "gcal": Connector("gcal", "Calendar", "calendar", "▦", "Spot deadlines and negotiation touchpoints.", _calendar),
    "contacts": Connector("contacts", "Contacts", "contacts", "☎", "Know who to reach — and let your agent text them.", _contacts),
}


def list_connectors() -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "kind": c.kind, "icon": c.icon, "blurb": c.blurb}
        for c in REGISTRY.values()
    ]


@op(name="integrations.learn", kind="tool")
def learn_from_source(source_id: str) -> LearnResult:
    conn = REGISTRY.get(source_id)
    if not conn:
        raise ValueError(f"Unknown connector: {source_id}")
    return conn.fetch()
