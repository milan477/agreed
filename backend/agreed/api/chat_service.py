"""Home chat + session orchestration for the new UX."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..agents.representation import RepresentationAgent
from ..domain.term_sheets import build_dynamic_scenario, get_scenario
from ..integrations.connectors import learn_from_source
from ..llm import chat_json, chat_text
from ..observability import op
from ..orchestration.conversation import ConversationalNegotiation
from ..persistence.sessions import create_session, get_by_invite, get_session, parse_invite_link, update_session
from ..persistence.store import UserScopedStore


def _default_profile() -> dict:
    return {
        "intent_summary": "",
        "style": "balanced",
        "constraints": "",
        "traits": [],
        "goals": [],
        "account_type": "individual",  # "individual" | "corporation"
        "voice_sample": "",  # last thing the user said, used to mirror their tone
        "phone": "",
        "email": "",
        "preferred_channel": "text",  # text | call | auto
        "outreach_enabled": True,
        "followup_delay_minutes": 2,
        "connections": [],   # connected data-source ids
        "learned_facts": [], # facts the agent learned from connectors
        "counterparties": [],
    }


def _extract_goals(message: str, existing: list[dict], account_type: str = "individual") -> list[dict]:
    """Heuristic goal detection from chat (works offline).

    Corporations only ever negotiate, so every detected goal is a negotiation.
    """
    corp = account_type == "corporation"
    text = message.lower()
    goals = list(existing)
    titles: set[str] = {g["title"].lower() for g in goals}

    patterns = [
        (r"\b(buy|purchase|procure|order)\b.+(?:bulk|shirts|software|platform|contract)", "negotiation"),
        (r"\b(sell|offer|provide)\b", "negotiation"),
        (r"\b(rent|lease|landlord|tenant)\b", "negotiation"),
        (r"\b(hire|employ|candidate|salary|contract|deal|supplier|vendor)\b", "negotiation"),
        (r"\b(participate|community|survey|residents|municipality|petition|town hall)\b", "participation"),
    ]
    for pat, kind in patterns:
        if re.search(pat, text):
            if corp:
                kind = "negotiation"
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
    m = re.search(r"\b(i want to|i need to|looking to|trying to|we need|we want)\s+(.{8,60})", text)
    if m and len(goals) == len(existing):
        title = m.group(2).strip(" .")
        if title.lower() not in titles:
            if corp:
                kind = "negotiation"
            else:
                kind = "participation" if ("participate" in text or "community" in text) else "negotiation"
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
    account_type = profile.get("account_type", "individual")
    old_ids = {g["id"] for g in profile.get("goals", [])}
    goals = _extract_goals(message, profile.get("goals", []), account_type)
    new_goals = [g for g in goals if g["id"] not in old_ids]
    profile = {**profile, "goals": goals}

    # Update constraints/style from message
    if any(w in message.lower() for w in ("budget", "under $", "max ", "timeline", "deadline")):
        profile["constraints"] = (profile.get("constraints", "") + " " + message).strip()[:300]
    if "aggressive" in message.lower():
        profile["style"] = "assertive"
    elif "relationship" in message.lower() or "preserve" in message.lower():
        profile["style"] = "relationship-preserving"

    # Keep a sample of how the user talks so the agent can mirror their voice
    # everywhere — in chat and later when it negotiates on their behalf.
    if len(message.strip()) >= 6:
        profile["voice_sample"] = message.strip()[:240]

    system = (
        "You are the user's own agent on agreed — an extension of them, not a separate persona. "
        "Mirror their voice precisely: match their tone, register, slang, punctuation and energy. "
        "If they write 'hey bro, need to sort a deal', you reply in that same casual register; if "
        "they're formal, you're formal. Learn who they are and what they want, acknowledge any goal "
        "they mention, and ask ONE focused follow-up about their targets, priorities or constraints. "
        "Never inject your own opinions or agenda. Keep it to 1-3 sentences."
    )
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:])
    reply = chat_text(
        system,
        f"User profile so far: {profile}\nAccount type: {account_type}\n\n"
        f"Conversation:\n{hist}\n\nUser: {message}\n\nReply in the user's own voice:",
        temperature=0.7,
    )
    if not reply:
        reply = _mirrored_fallback(message, goals, profile, account_type)

    if len(message) > 20 and not profile.get("intent_summary"):
        profile["intent_summary"] = message[:280]

    intent = _validate_intent(message, new_goals, goals, account_type)
    suggested = _suggested_questions(message, profile, new_goals, account_type)

    return {
        "reply": reply.strip(),
        "profile": profile,
        "new_goals": new_goals,
        "intent": intent,
        "suggested_questions": suggested,
    }


def _validate_intent(message: str, new_goals: list[dict], goals: list[dict], account_type: str) -> dict:
    """Surface a confirmable intent so the chat can validate before acting.

    CopilotKit renders this as an inline confirmation card; offline we still
    detect intent heuristically so the UX is identical.
    """
    if new_goals:
        g = new_goals[-1]
        return {
            "detected": True,
            "summary": g["title"],
            "kind": g["kind"],
            "goal_id": g["id"],
            "confidence": 0.82,
            "needs_confirmation": True,
            "prompt": f"Want me to set up “{g['title']}” as a {g['kind']}?",
        }
    return {"detected": False}


def _suggested_questions(message: str, profile: dict, new_goals: list[dict], account_type: str) -> list[str]:
    """Dynamically propose the next useful things to tell the agent."""
    if llm_available_safe():
        sys = (
            "You generate up to 3 very short follow-up prompts (max 7 words each) that the USER could "
            "tap to tell their negotiation agent more. Return JSON: {\"questions\": [\"...\"]}. "
            "Base them on what's still unknown (targets, walk-away, counterparty, deadline, priorities)."
        )
        usr = f"Account: {account_type}. Profile: {profile}. Latest message: {message}."
        data = chat_json(sys, usr, max_tokens=160)
        if data and isinstance(data.get("questions"), list):
            qs = [str(q).strip() for q in data["questions"] if str(q).strip()][:3]
            if qs:
                return qs
    have_goal = bool(profile.get("goals"))
    constraints = profile.get("constraints", "")
    out: list[str] = []
    if new_goals or have_goal:
        if "budget" not in constraints.lower() and "$" not in constraints:
            out.append("Set my budget / walk-away")
        out.append("Who's on the other side?")
        out.append("What matters most to me")
    else:
        out = ["I want to negotiate a deal", "I want a say in a decision", "Learn about me first"]
    return out[:3]


def llm_available_safe() -> bool:
    try:
        from ..llm import llm_available
        return llm_available()
    except Exception:
        return False


def connect_source(source_id: str, st: UserScopedStore) -> dict:
    """Link a data source; the agent learns from it and reacts personally."""
    result = learn_from_source(source_id)
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    account_type = profile.get("account_type", "individual")

    conns = set(profile.get("connections", []))
    conns.add(source_id)
    profile["connections"] = sorted(conns)

    learned = profile.get("learned_facts", [])
    for f in result.facts:
        learned.append({**f, "source": source_id})
    profile["learned_facts"] = learned[-40:]
    profile["traits"] = sorted(set(profile.get("traits", []) + result.traits))
    profile["counterparties"] = sorted(set(profile.get("counterparties", []) + result.counterparties))
    if result.constraints:
        merged = (profile.get("constraints", "") + " " + "; ".join(result.constraints)).strip()
        profile["constraints"] = merged[:400]
    if result.tone and not profile.get("tone_hint"):
        profile["tone_hint"] = result.tone

    goals = profile.get("goals", [])
    titles = {g["title"].lower() for g in goals}
    new_goals: list[dict] = []
    for g in result.suggested_goals:
        if g["title"].lower() in titles:
            continue
        kind = "negotiation" if account_type == "corporation" else g.get("kind", "negotiation")
        ng = {
            "id": uuid.uuid4().hex[:10],
            "title": g["title"],
            "kind": kind,
            "status": "open",
            "from_connector": source_id,
            "other_party_label": g.get("other_party_label"),
        }
        goals.append(ng)
        new_goals.append(ng)
        titles.add(g["title"].lower())
    profile["goals"] = goals

    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    return {"profile": profile, "learned": result.to_dict(), "new_goals": new_goals}


def _detect_register(message: str) -> str:
    """Cheap tone sniff so the offline fallback still mirrors the user a little."""
    t = message.lower()
    casual = any(w in t for w in ("bro", "dude", "hey", "yo", "gonna", "wanna", "lol", "tbh", "sup", "y'all"))
    return "casual" if casual else "neutral"


def _mirrored_fallback(message: str, goals: list[dict], profile: dict, account_type: str) -> str:
    register = _detect_register(message)
    casual = register == "casual"
    has_new_goal = goals and goals[-1]["id"] not in {g.get("id") for g in profile.get("goals", [])[:-1]}
    if has_new_goal:
        g = goals[-1]
        if casual:
            return f"Got it bro — locking in \"{g['title']}\". What's your dream outcome here, and where's your hard line?"
        return f"Noted: \"{g['title']}\". What matters most to you there, and what would make you walk away?"
    if not profile.get("intent_summary"):
        if account_type == "corporation":
            return ("Tell me what deal you're trying to get done and I'll handle it."
                    if not casual else "Aight — what deal are we trying to close? I got you.")
        return ("Tell me what you're trying to get done — a deal to negotiate or something you want a say in — and I'll take it from there."
                if not casual else "What're we trying to do? A deal to negotiate or something you wanna weigh in on? I'm on it.")
    return ("Got it. Anything else I should know about your targets or limits before I get to work?"
            if not casual else "Cool. Anything else I should know before I jump on this?")


def new_session_from_goal(user_id: str, goal: dict, st: UserScopedStore) -> dict:
    kind = goal.get("kind", "negotiation")
    prof_rec = next((r for r in st.list("user_profile")), None)
    account_type = (prof_rec["data"].get("account_type") if prof_rec else None) or "individual"
    if account_type == "corporation":
        kind = "negotiation"
    session = create_session(user_id, {
        "title": goal["title"],
        "kind": kind,
        "account_type": account_type,
        "status": "agent" if kind == "participation" else "setup",
        "framework": "pareto",
        "max_rounds": 16,
        "use_custom_agent": False,
        "custom_agent_url": "",
        # negotiation -> structured by default; participation is a deliberation (textual)
        "interaction_mode": "textual" if kind == "participation" else "structured",
        "targets": None,
        "viewpoints": None,
        "parties": {
            user_id: {"role": "Buyer" if kind == "negotiation" else "Participant", "submitted": False, "label": "You"},
        },
        "other_party_id": None,
        "other_party_label": goal.get("other_party_label") or ("Host organization" if kind == "participation" else None),
        "goal_id": goal.get("id"),
        "negotiation_result": None,
        "brief": None,
        "tentative_agreements": [],
    })
    st.put("session_ref", {"session_id": session["session_id"], "title": session["title"], "kind": kind}, ref=session["session_id"])
    return session


def add_tentative_agreement(session_id: str, user_id: str, text: str, st: UserScopedStore) -> dict:
    """Add a tentative (non-binding) point both sides can converge on."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Agreement text is required")
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    items = session.setdefault("tentative_agreements", [])
    items.append({
        "id": uuid.uuid4().hex[:8],
        "text": text[:280],
        "status": "tentative",  # tentative | accepted | rejected
        "added_by": user_id,
    })
    return update_session(session_id, session)


def set_tentative_status(session_id: str, item_id: str, status: str, st: UserScopedStore) -> dict:
    if status not in ("tentative", "accepted", "rejected"):
        raise ValueError("Invalid status")
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    for it in session.get("tentative_agreements", []):
        if it["id"] == item_id:
            it["status"] = status
            break
    else:
        raise ValueError("Tentative agreement not found")
    return update_session(session_id, session)


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


def set_account_type(account_type: str, st: UserScopedStore) -> dict:
    """Persist whether the user is an individual or a corporation."""
    account_type = "corporation" if account_type == "corporation" else "individual"
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    profile["account_type"] = account_type
    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    return profile


def default_targets() -> dict:
    """Sensible starting values the user tweaks during the probe."""
    sc = get_scenario()
    bl = sc.buyer["limits"]
    return {
        "price": {"target": bl["price"]["target"], "walk_away": bl["price"]["walk_away"], "importance": 5},
        "delivery_weeks": {"target": bl["delivery_weeks"]["target"], "walk_away": bl["delivery_weeks"]["walk_away"], "importance": 2},
        "warranty_months": {"target": bl["warranty_months"]["target"], "walk_away": bl["warranty_months"]["walk_away"], "importance": 4},
        "support_hours": {"target": bl["support_hours"]["target"], "walk_away": bl["support_hours"]["walk_away"], "importance": 2},
        "payment_terms": {"target": bl["payment_terms"]["target"], "importance": 3},
    }


def save_probe(
    session_id: str,
    user_id: str,
    st: UserScopedStore,
    *,
    targets: dict | None = None,
    viewpoints: list[dict] | None = None,
    interaction_mode: str | None = None,
) -> dict:
    """Save the values the agent probed for, then build the brief (-> prepare)."""
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    if interaction_mode in ("structured", "textual"):
        session["interaction_mode"] = interaction_mode
    if session.get("kind") == "negotiation":
        session["targets"] = targets or session.get("targets") or default_targets()
    else:
        session["viewpoints"] = viewpoints or session.get("viewpoints") or []
        session["interaction_mode"] = "textual"
    update_session(session_id, session)
    return prepare_session(session_id, user_id, st)


def prepare_session(session_id: str, user_id: str, st: UserScopedStore) -> dict:
    """Step 2.5: research + build negotiation brief, then move to prepare status."""
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")

    rep = RepresentationAgent(get_scenario())
    prof_rec = next((r for r in st.list("user_profile")), None)
    party = "Buyer" if session.get("kind") == "negotiation" else "Participant"
    profile = prof_rec["data"] if prof_rec else {}
    profile = {
        **profile,
        "party": party,
        "purpose": session["title"],
        "approved": True,
        "style": profile.get("style", "balanced"),
        "constraints": profile.get("constraints", ""),
    }
    brief = rep.build_brief(party, profile, self_improved=False)
    # Reflect the user's *own* probed targets into the brief so it isn't generic.
    if session.get("kind") == "negotiation" and session.get("targets"):
        sc = build_dynamic_scenario(session["targets"], session["title"])
        from ..domain.term_sheets import DIM_LABELS
        ranked = sc.buyer["priority_ranking"]
        brief["ranked_priorities"] = [DIM_LABELS.get(p, p) for p in ranked]
        brief["walk_away_points"] = sc.buyer["limits"]
        brief["opening_position"] = {d: sc.buyer["limits"][d]["target"] for d in sc.buyer["limits"]}
    elif session.get("viewpoints"):
        brief["ranked_priorities"] = [
            v.get("topic", "Viewpoint") for v in session["viewpoints"] if v.get("topic")
        ] or brief.get("ranked_priorities", [])
        brief["strategy"] = "Represent the user's stated viewpoints faithfully and seek common ground."
    session["brief"] = brief
    session["status"] = "prepare"
    session["prepared_by"] = user_id
    return update_session(session_id, session)


def confirm_agent_choice(
    session_id: str,
    user_id: str,
    st: UserScopedStore,
    *,
    use_custom_agent: bool,
    custom_agent_url: str = "",
) -> dict:
    """Save agent choice, then move to the probe step (targets / viewpoints)."""
    session = get_session(session_id)
    if not session:
        raise ValueError("Session not found")
    if use_custom_agent and not custom_agent_url.strip():
        raise ValueError("External agent URL is required")

    session["use_custom_agent"] = use_custom_agent
    session["custom_agent_url"] = custom_agent_url.strip()
    session["status"] = "probe"
    if session.get("kind") == "negotiation" and not session.get("targets"):
        session["targets"] = default_targets()
    return update_session(session_id, session)


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
    session["status"] = "running"

    prof_rec = next((r for r in st.list("user_profile")), None)
    voice = (prof_rec["data"].get("voice_sample", "") if prof_rec else "")

    kind = session.get("kind", "negotiation")
    mode = session.get("interaction_mode") or ("structured" if kind == "negotiation" else "textual")
    user_label = "Your agent"
    counter_label = session.get("other_party_label") or "Counterparty agent"

    if kind == "negotiation" and session.get("targets"):
        scenario = build_dynamic_scenario(session["targets"], session["title"])
    else:
        scenario = get_scenario()

    convo = ConversationalNegotiation(
        mode=mode,
        scenario=scenario,
        topic=session["title"],
        user_label=user_label,
        counter_label=counter_label,
        user_voice=voice,
        viewpoints=session.get("viewpoints") or [],
        max_rounds=10,
        framework=session.get("framework", "pareto"),
    )
    payload = convo.run()
    rid = st.put("negotiation", payload, ref=payload["trace_id"])
    payload["negotiation_id"] = rid
    payload["deal_terms"] = payload.get("agreement_terms")
    session["negotiation_result"] = payload
    session["status"] = "review"
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


def update_contact_info(
    st: UserScopedStore,
    *,
    phone: str | None = None,
    email: str | None = None,
    preferred_channel: str | None = None,
    outreach_enabled: bool | None = None,
    followup_delay_minutes: float | None = None,
) -> dict:
    """Save reach-out preferences and bind phone for inbound SMS/voice."""
    from ..messaging.phone_registry import bind_phone

    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()

    if phone is not None:
        profile["phone"] = phone.strip()
        bound = bind_phone(st.user_id, profile["phone"])
        if bound:
            profile["phone"] = bound
    if email is not None:
        profile["email"] = email.strip()
    if preferred_channel is not None:
        ch = preferred_channel if preferred_channel in ("text", "call", "auto") else "text"
        profile["preferred_channel"] = ch
    if outreach_enabled is not None:
        profile["outreach_enabled"] = outreach_enabled
    if followup_delay_minutes is not None:
        profile["followup_delay_minutes"] = max(0.5, float(followup_delay_minutes))

    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    return profile
