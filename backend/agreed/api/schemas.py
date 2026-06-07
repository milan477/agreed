"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UserIn(BaseModel):
    email: str = ""
    name: str = ""


class OnboardingIn(BaseModel):
    party: str = Field(description="Buyer | Seller")
    purpose: str
    answers: dict[str, str] = {}


class ApproveIn(BaseModel):
    record_id: str


class BriefIn(BaseModel):
    party: str
    profile_id: str
    self_improved: bool = False


class StrategyIn(BaseModel):
    concession_rate: float | None = None
    acceptance_threshold: float | None = None
    threshold_decay: float | None = None
    anchor_aggressiveness: float | None = None
    prompt_addendum: str | None = None


class NegotiationIn(BaseModel):
    framework: str = "pareto"
    max_rounds: int = 16
    use_moderator: bool = True
    buyer_strategy: StrategyIn | None = None
    seller_strategy: StrategyIn | None = None


class SelfImproveIn(BaseModel):
    party: str = "Buyer"
    framework: str = "pareto"
    metric: str = "party_utility"


class SignIn(BaseModel):
    negotiation_id: str
    signature: str
    party: str


class ChatIn(BaseModel):
    message: str
    history: list[dict[str, str]] = []
    conversation_id: str | None = None


class JoinInviteIn(BaseModel):
    link: str


class SessionCreateIn(BaseModel):
    goal_id: str | None = None
    title: str
    kind: str = "negotiation"  # negotiation | participation
    other_party_label: str | None = None


class SessionUpdateIn(BaseModel):
    other_party_id: str | None = None
    other_party_label: str | None = None
    framework: str | None = None
    max_rounds: int | None = None
    use_custom_agent: bool | None = None
    custom_agent_url: str | None = None
    status: str | None = None


class ContactIn(BaseModel):
    user_id: str
    label: str


class AgentChoiceIn(BaseModel):
    use_custom_agent: bool = False
    custom_agent_url: str = ""


class AccountTypeIn(BaseModel):
    account_type: str = "individual"  # individual | corporation


class ProbeIn(BaseModel):
    targets: dict[str, Any] | None = None
    viewpoints: list[dict[str, Any]] | None = None
    interaction_mode: str | None = None  # structured | textual


class MessageDraftIn(BaseModel):
    recipient: str = ""
    purpose: str
    channel: str = "text"  # text | call


class MessageSendIn(BaseModel):
    recipient: str
    body: str = ""
    channel: str = "text"  # text | call


class TentativeIn(BaseModel):
    text: str


class TentativeStatusIn(BaseModel):
    item_id: str
    status: str  # tentative | accepted | rejected


class ContactInfoIn(BaseModel):
    phone: str | None = None
    email: str | None = None
    preferred_channel: str | None = None  # text | call | auto
    outreach_enabled: bool | None = None
    followup_delay_minutes: float | None = None


class FollowupScheduleIn(BaseModel):
    channel: str = "text"
    purpose: str
    delay_minutes: float = 2
    open_question: str = ""
