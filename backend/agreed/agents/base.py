"""A2A protocol message format + agent capability eval gate.

All inter-agent communication flows through `A2AMessage`. This is the entry point
that lets a party plug in their own agent (negotiation mode): any agent that can
speak A2A and passes the standardized capability eval may participate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ..observability import op, record_event

# A2A performative / message kinds used across the platform.
A2A_KINDS = (
    "propose",          # a full counteroffer
    "accept",           # accept the other side's last proposal
    "inform",           # share information (research, summary)
    "request",          # ask for something (e.g. user follow-up)
    "evaluate",         # critic scoring result
    "decision",         # moderator ruling / settlement
)


@dataclass
class A2AMessage:
    """A single A2A protocol message."""

    sender: str
    recipient: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    reply_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@op(name="a2a.send", kind="a2a")
def send(msg: A2AMessage) -> A2AMessage:
    """Record an A2A message on the trace and return it (transport is in-process)."""
    record_event(
        f"a2a:{msg.kind}",
        kind="a2a",
        sender=msg.sender,
        recipient=msg.recipient,
        conversation_id=msg.conversation_id,
    )
    return msg


class Agent:
    """Base class for platform agents. Subclasses implement domain behavior."""

    role: str = "agent"

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.role

    def __repr__(self) -> str:  # keeps Weave traces readable
        return f"<{type(self).__name__} name={self.name!r}>"


# ── Plug-in agent capability gate ─────────────────────────────────────────────


CAPABILITY_DIMENSIONS = ("speaks_a2a", "returns_valid_terms", "respects_bounds", "responsive")


@op(name="agent.capability_eval", kind="eval")
def capability_eval(agent_card: dict, *, probe_fn=None) -> dict[str, Any]:
    """Standardized gate a plug-in (A2A) agent must pass before it can negotiate.

    `agent_card` is the agent's self-description (A2A agent card). `probe_fn`, if
    provided, is called with a sample task and must return a valid proposal dict;
    used to verify the agent actually behaves. Returns a pass/fail report.
    """
    checks: dict[str, bool] = {}
    checks["speaks_a2a"] = bool(agent_card.get("protocols")) and "a2a" in [
        p.lower() for p in agent_card.get("protocols", [])
    ]

    sample = None
    if probe_fn is not None:
        try:
            sample = probe_fn()
        except Exception:
            sample = None

    required = {"price", "delivery_weeks", "payment_terms", "warranty_months", "support_hours"}
    checks["returns_valid_terms"] = isinstance(sample, dict) and required.issubset(sample.keys())
    checks["respects_bounds"] = bool(sample) and isinstance(sample.get("price"), (int, float))
    checks["responsive"] = sample is not None or probe_fn is None

    passed = all(checks.values())
    record_event("capability_eval", kind="eval", passed=passed, checks=checks)
    return {"passed": passed, "checks": checks, "agent_card": agent_card}
