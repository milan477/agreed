"""Home chat + session orchestration for the new UX."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..agents.representation import RepresentationAgent
from ..domain.term_sheets import get_scenario
from ..llm import chat_text
from ..observability import op
from ..orchestration.graph import NegotiationOrchestrator
from ..persistence.sessions import create_session, get_by_invite, get_session, parse_invite_link, update_session
from ..persistence.store import UserScopedStore


def _default_profile() -> dict:
    return {
        "intent_summary": "",
        "style": "balanced",
        "constraints": "",
        "traits": [],
        "goals": [],
    }


def _extract_goals(message: str, existing: list[dict]) -> list[dict]:
    """Heuristic goal detection from chat (works offline)."""
    text = message.lower()
    goals = list(existing)
    titles: set[str] = {g["title"].lower() for g in goals}

    patterns = [
        (r"\b(buy|purchase|procure|order)\b.+(?:bulk|shirts|software|platform|contract)", "negotiation"),
        (r"\b(sell|offer|provide)\b", "negotiation"),
        (r"\b(rent|lease|landlord|tenant)\b", "negotiation"),
        (r"\b(hire|employ|candidate|salary)\b", "negotiation"),
        (r"\b(participate|community|survey|residents|municipality)\b", "participation"),
    ]
    for pat, kind in patterns:
        if re.search(pat, text):
            title = message.strip()[:80] or ("New " + kind)
            key = title.lower()
            if key not in titles:
                goals.append({
                    "id": uuid.uuid4().hex[:10],
                    "title": title,
                    "kind": kind,
                    "status": "open",
                    "created_from_chat": True,
                })
                titles.add(key)
            break

    # Generic "I want to ..." / "I need to ..."
    m = re.search(r"\b(i want to|i need to|looking to|trying to)\s+(.{8,60})", text)
    if m and len(goals) == len(existing):
        title = m.group(2).strip(" .")
        if title.lower() not in titles:
            kind = "participation" if "participate" in text or "community" in text else "negotiation"
            goals.append({
                "id": uuid.uuid4().hex[:10],
                "title": title[0].upper() + title[1:],
                "kind": kind,
                "status": "open",
                "created_from_chat": True,
            })
    return goals


@op(name="chat.represent", kind="agent")
def chat_with_agent(message: str, history: list[dict], profile: dict) -> dict:
    old_ids = {g["id"] for g in profile.get("goals", [])}
    goals = _extract_goals(message, profile.get("goals", []))
    new_goals = [g for g in goals if g["id"] not in old_ids]
    profile = {**profile, "goals": goals}

    # Update constraints/style from message
    if any(w in message.lower() for w in ("budget", "under $", "max ", "timeline", "deadline")):
        profile["constraints"] = (profile.get("constraints", "") + " " + message).strip()[:300]
    if "aggressive" in message.lower():
        profile["style"] = "assertive"
    elif "relationship" in message.lower() or "preserve" in message.lower():
        profile["style"] = "relationship-preserving"

    system = (
        "You are the user's representation agent on agreed. Learn who they are and what they want. "
        "Be calm, concise, trustworthy. Never inject opinions. When they mention a goal, acknowledge it "
        "and ask one focused follow-up about priorities or constraints. 2-3 sentences max."
    )
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:])
    reply = chat_text(system, f"Profile so far: {profile}\n\nHistory:\n{hist}\n\nUser: {message}\n\nReply:")
    if not reply:
        if goals and goals[-1]["id"] not in {g.get("id") for g in profile.get("goals", [])[:-1]}:
            g = goals[-1]
            reply = (
                f"I noted a new {g['kind']} goal: \"{g['title']}\". "
                "What matters most to you there, and what would make you walk away?"
            )
        elif not profile.get("intent_summary"):
            reply = (
                "Tell me what you're trying to achieve — a purchase, a sale, a lease, "
                "or a community participation — and I'll represent you."
            )
        else:
            reply = "Got it. Anything else I should know about your priorities or constraints before we proceed?"

    if len(message) > 20 and not profile.get("intent_summary"):
        profile["intent_summary"] = message[:280]

    return {"reply": reply.strip(), "profile": profile, "new_goals": new_goals}


def new_session_from_goal(user_id: str, goal: dict, st: UserScopedStore) -> dict:
    kind = goal.get("kind", "negotiation")
    session = create_session(user_id, {
        "title": goal["title"],
        "kind": kind,
        "status": "rules" if kind == "participation" else "setup",
        "framework": "pareto",
        "max_rounds": 16,
        "use_custom_agent": False,
        "custom_agent_url": "",
        "parties": {
            user_id: {"role": "Buyer" if kind == "negotiation" else "Participant", "submitted": False, "label": "You"},
        },
        "other_party_id": None,
        "other_party_label": goal.get("other_party_label") or ("Host organization" if kind == "participation" else None),
        "goal_id": goal.get("id"),
        "negotiation_result": None,
        "brief": None,
    })
    st.put("session_ref", {"session_id": session["session_id"], "title": session["title"], "kind": kind}, ref=session["session_id"])
    return session


def join_via_invite(user_id: str, invite_input: str, st: UserScopedStore) -> dict:
    code = parse_invite_link(invite_input)
    if not code:
        raise ValueError("Invalid invitation link")
    session = get_by_invite(code)
    if not session:
        raise ValueError("Invitation not found")
    sid = session["session_id"]
    parties = session.setdefault("parties", {})
    if user_id not in parties:
        role = "Seller" if session.get("kind") == "negotiation" else "Participant"
        parties[user_id] = {"role": role, "submitted": False, "label": f"Party {len(parties) + 1}"}
        session = update_session(sid, session)
    st.put("session_ref", {"session_id": sid, "title": session["title"], "kind": session["kind"]}, ref=sid)
    return session


def submit_agent(session_id: str, user_id: str, st: UserScopedStore) -> dict:
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    parties = session.setdefault("parties", {})
    if user_id not in parties:
        raise ValueError("Not a party in this session")
    parties[user_id]["submitted"] = True
    # Demo: single user gets a platform counterparty so negotiation can start
    if len(parties) == 1:
        parties["platform_counterparty"] = {
            "role": "Seller" if session.get("kind") == "negotiation" else "Host",
            "submitted": True,
            "label": session.get("other_party_label") or "Counterparty (platform agent)",
        }
    session["status"] = "ready" if all(p.get("submitted") for p in parties.values()) else "waiting"
    session = update_session(session_id, session)
    st.put("session_ref", {"session_id": session_id, "submitted": True}, ref=session_id, record_id=f"ref_{session_id}")

    if session["status"] == "ready":
        session = _run_session_negotiation(session, st)
    return session


def _run_session_negotiation(session: dict, st: UserScopedStore) -> dict:
    from ..observability import init_observability

    init_observability()
    rep = RepresentationAgent(get_scenario())
    host = session["host_user_id"]
    brief = rep.build_brief("Buyer", {"party": "Buyer", "purpose": session["title"], "approved": True})
    session["brief"] = brief
    session["status"] = "running"

    orch = NegotiationOrchestrator(framework=session.get("framework", "pareto"), max_rounds=session.get("max_rounds", 16))
    result = orch.run()
    payload = result.to_dict()
    session["negotiation_result"] = payload
    session["status"] = "review"
    st.put("negotiation", payload, ref=result.trace_id)
    return update_session(session["session_id"], session)


def list_user_sessions(st: UserScopedStore) -> list[dict]:
    refs = st.list("session_ref")
    out = []
    for ref in refs:
        sid = ref["data"].get("session_id") or ref.get("ref")
        if sid:
            s = get_session(sid)
            if s:
                out.append(s)
    return out


def list_contacts(st: UserScopedStore) -> list[dict]:
    return [r["data"] for r in st.list("contact")]
