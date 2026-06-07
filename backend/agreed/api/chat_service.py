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


# Intent leads ("I want to…", "wanna…") and bare action verbs ("buy a car").
_INTENT_LEAD = re.compile(
    r"\b(?:i\s+)?(?:want(?:ed)?\s+to|wanna|gonna|need(?:ed)?\s+to|would\s+like\s+to|"
    r"i'?d\s+like\s+to|looking\s+to|trying\s+to|hoping\s+to|plan(?:ning)?\s+to|"
    r"we\s+(?:want|need)\s+to)\s+(.+)",
    re.I,
)
_ACTION = re.compile(
    r"\b(buy|purchase|procure|order|sell|offer|lease|rent|hire|renew|"
    r"renegotiate|negotiate|acquire|book)\b\s+(.+)",
    re.I,
)
_PARTICIPATION_WORDS = (
    "participate", "community", "survey", "residents", "municipality", "petition",
    "town hall", "council", "hoa", "weigh in", "say in", "deliberat", "rezoning",
)


def _detect_kind(text: str, corp: bool) -> str:
    if corp:
        return "negotiation"
    if any(w in text for w in _PARTICIPATION_WORDS):
        return "participation"
    return "negotiation"


def _clean_title(message: str, kind: str) -> str:
    """Turn a free-form sentence into a short, clean goal title."""
    text = re.sub(
        r"^\s*(yo|hey|hi|hello|ok|okay|so|um|uh|well|please|pls|alright|aight)[\s,!]+",
        "", message.strip(), flags=re.I,
    )
    core = ""
    m = _INTENT_LEAD.search(text)
    if m:
        core = m.group(1)
    else:
        m2 = _ACTION.search(text)
        if m2:
            core = f"{m2.group(1)} {m2.group(2)}"
    if not core:
        core = text
    # Drop trailing price/constraint clauses so the title stays about the thing.
    core = re.split(
        r"\s*(?:,|;|\.|—|\bbudget\b|\bunder\b|\bmax\b|\bfor \$|\bat \$|\baround \$|\bbecause\b|\bso that\b)",
        core, maxsplit=1, flags=re.I,
    )[0]
    core = core.strip(" .!?,")
    words = core.split()
    if len(words) > 9:
        core = " ".join(words[:9])
    if not core:
        return "New " + kind
    return core[0].upper() + core[1:]


def _extract_goals(message: str, existing: list[dict], account_type: str = "individual") -> list[dict]:
    """Heuristic goal detection from chat (works offline).

    A goal is created when the message expresses an actionable intent. Once we
    already track a goal, only an *explicit* new intent ("I want to…") starts
    another, so follow-up answers (prices, priorities) don't spawn stray goals.
    Corporations only ever negotiate.
    """
    corp = account_type == "corporation"
    text = message.lower()
    goals = list(existing)
    titles: set[str] = {g["title"].lower() for g in goals}

    has_lead = bool(_INTENT_LEAD.search(text))
    has_action = bool(_ACTION.search(text)) or any(w in text for w in _PARTICIPATION_WORDS)
    if not (has_lead or has_action):
        return goals
    if existing and not has_lead:
        return goals

    kind = _detect_kind(text, corp)
    title = _clean_title(message, kind)
    if title.lower() not in titles:
        goals.append({
            "id": uuid.uuid4().hex[:10],
            "title": title,
            "kind": kind,
            "status": "open",
            "created_from_chat": True,
        })
    return goals


_CHAT_SYSTEM = """You are the user's own AI agent on "agreed" — a platform where every party is represented by an AI agent and negotiations happen agent-to-agent. You are an extension of the user, not a separate persona.

HOW AGREED WORKS — follow this strictly:
- You NEVER search for, find, browse, or source the other party or the item (a seller, buyer, vendor, landlord, a specific car, etc.). The platform does not go shopping for the user.
- A negotiation starts only when an "agreed?" session is created and the user shares an agreement link with the other party. That party opens the link, their own agent joins, and the two agents negotiate to an agreement.
- Your job in this chat: (1) understand the user's objective in THEIR voice, (2) probe their preferences/targets, (3) once you have enough, tell them you're setting up an "agreed?" session that they can share a link from to bring in the other party. Never offer to find or contact the counterparty yourself.

VOICE: Mirror the user's tone, register, slang, punctuation and energy exactly (if they say "yo bro", you match that). Keep replies to 1-2 sentences. Acknowledge what they just told you, then ask only for the NEXT missing piece — never re-ask something already answered.

WHAT TO COLLECT:
- negotiation: ideal/target price, walk-away (hard limit), and what matters most (priorities).
- participation: the user's stance and the specific points to push for.

OUTPUT — respond with ONLY a JSON object, no prose:
{
  "reply": "your next message, in the user's voice",
  "goal": {"title": "short clean objective like 'Buy a used car'", "kind": "negotiation" or "participation"} or null,
  "intake": {"target": number or null, "walk_away": number or null, "priorities": ["..."], "counterparty": "name only if the user named one, else null"},
  "ready": true or false,
  "suggested": ["up to 3 short FIRST-PERSON quick replies the user could tap; a fill-in template may end with the … character"]
}

RULES:
- Reuse the Current goal's exact title unless the user clearly switches objective; set "goal" to null when the objective is unchanged.
- "intake" MUST merge with what's already collected (echo known values back, add new ones).
- "ready" is true only when there is enough to set up the session — negotiation: target AND walk-away AND at least one priority; participation: a clear stance.
- When "ready" is true, "reply" must say you're setting up their agreed? session and they'll get a link to send the other party. Do NOT say you'll find, search, or contact anyone.
- For a corporation account, "kind" is always "negotiation"."""


@op(name="chat.represent", kind="agent")
def chat_with_agent(message: str, history: list[dict], profile: dict) -> dict:
    account_type = profile.get("account_type", "individual")
    goals: list[dict] = list(profile.get("goals", []))
    profile = {**profile, "goals": goals}

    if "aggressive" in message.lower():
        profile["style"] = "assertive"
    elif "relationship" in message.lower() or "preserve" in message.lower():
        profile["style"] = "relationship-preserving"
    if len(message.strip()) >= 6:
        profile["voice_sample"] = message.strip()[:240]

    active_before = goals[-1] if goals else None

    # LLM-first: a single structured turn does the text processing (understand,
    # probe, extract intake, decide readiness). Heuristics are only a fallback.
    data = _llm_turn(message, history, profile, account_type, active_before)

    if isinstance(data, dict) and data.get("reply"):
        reply, active_goal, new_goals, ready, suggested = _apply_llm_turn(data, goals, account_type)
    else:
        old_ids = {g["id"] for g in goals}
        goals[:] = _extract_goals(message, list(goals), account_type)
        new_goals = [g for g in goals if g["id"] not in old_ids]
        active_goal = goals[-1] if goals else None
        changed = _update_intake(message, active_goal) if active_goal is not None else []
        reply = _statemachine_reply(message, active_goal, account_type, changed, bool(new_goals))
        ready = _is_ready(active_goal)
        suggested = _suggested_questions(active_goal, account_type)

    _sync_constraints(profile, active_goal)
    if len(message) > 16 and not profile.get("intent_summary"):
        profile["intent_summary"] = message[:280]
    profile["goals"] = goals

    intent = _intent_for(active_goal, ready)

    return {
        "reply": (reply or "").strip(),
        "profile": profile,
        "new_goals": new_goals,
        "intent": intent,
        "suggested_questions": suggested,
    }


def _llm_turn(
    message: str, history: list[dict], profile: dict, account_type: str, active: dict | None
) -> dict | None:
    cur_goal = {"title": active["title"], "kind": active.get("kind")} if active else None
    intake = (active or {}).get("intake", {})
    system = _CHAT_SYSTEM
    recalled = profile.get("recalled_memories") or []
    if recalled:
        system += f"\n\nRecalled preferences about this user (use them): {recalled[:3]}"
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:])
    audience = (
        "corporations only ever negotiate" if account_type == "corporation"
        else "individuals can negotiate or participate"
    )
    user = (
        f"Account type: {account_type} ({audience}).\n"
        f"Current goal: {cur_goal}\n"
        f"Collected intake so far: {intake}\n"
        f"Recent conversation:\n{hist or '(none yet)'}\n"
        f"Latest user message: {message}\n\n"
        "Return the JSON now."
    )
    return chat_json(system, user, temperature=0.6, max_tokens=400)


def _coerce_num(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    if not s:
        return None
    mult = 1
    if s.endswith("k"):
        mult, s = 1000, s[:-1].strip()
    try:
        return int(round(float(s) * mult))
    except Exception:
        return None


def _apply_llm_turn(
    data: dict, goals: list[dict], account_type: str
) -> tuple[str, dict | None, list[dict], bool, list[str]]:
    """Apply the LLM's structured turn to the goal list and intake."""
    old_ids = {g["id"] for g in goals}
    active = goals[-1] if goals else None

    g = data.get("goal")
    if isinstance(g, dict) and g.get("title"):
        title = str(g["title"]).strip()[:80]
        kind = g.get("kind") if g.get("kind") in ("negotiation", "participation") else "negotiation"
        if account_type == "corporation":
            kind = "negotiation"
        match = next((ex for ex in goals if ex["title"].strip().lower() == title.lower()), None)
        if match is None:
            active = {
                "id": uuid.uuid4().hex[:10],
                "title": title[0].upper() + title[1:],
                "kind": kind,
                "status": "open",
                "created_from_chat": True,
            }
            goals.append(active)
        else:
            active = match
            active["kind"] = kind

    if active is not None:
        intake = active.setdefault(
            "intake", {"target": None, "walk_away": None, "priorities": [], "counterparty": None}
        )
        src = data.get("intake") or {}
        t, w = _coerce_num(src.get("target")), _coerce_num(src.get("walk_away"))
        if t is not None:
            intake["target"] = t
        if w is not None:
            intake["walk_away"] = w
        for p in src.get("priorities") or []:
            p = str(p).strip()
            if p and p.lower() not in [x.lower() for x in intake["priorities"]]:
                intake["priorities"].append(p)
        cp = src.get("counterparty")
        if cp and str(cp).strip().lower() not in ("", "null", "none", "unknown"):
            intake["counterparty"] = str(cp).strip()
        if (
            active.get("kind") == "negotiation"
            and intake["target"] and intake["walk_away"]
            and intake["target"] > intake["walk_away"]
        ):
            intake["target"], intake["walk_away"] = intake["walk_away"], intake["target"]

    new_goals = [g2 for g2 in goals if g2["id"] not in old_ids]
    reply = str(data.get("reply") or "")
    # Trust the LLM, but never get stuck: if we objectively have enough, offer setup.
    ready = bool(data.get("ready")) or _is_ready(active)
    suggested = [str(s).strip() for s in (data.get("suggested") or []) if str(s).strip()][:3]
    if not suggested:
        suggested = _suggested_questions(active, account_type)
    return reply, active, new_goals, ready, suggested


def _intent_for(active: dict | None, ready: bool) -> dict:
    if active and ready:
        return {
            "detected": True,
            "summary": active["title"],
            "kind": active.get("kind", "negotiation"),
            "goal_id": active["id"],
            "confidence": 0.92,
            "needs_confirmation": True,
            "prompt": f"Set up your agreed? session for “{active['title']}” so you can share a link with the other party?",
        }
    return {"detected": False}


# ── Conversational intake state machine ──────────────────────────────────────
# Drives a real, progressing conversation even with no LLM key. Each turn we
# parse what the user said into the active goal's `intake`, acknowledge it, then
# ask for the next thing we still need.

_WALK_WORDS = (
    "max ", "maximum", "cap", "ceiling", "no more than", "most i", "most i'd",
    "walk away", "walk-away", "up to", "at most", "hard limit", "limit",
)
_TARGET_WORDS = (
    "under", "below", "around", "ideally", "target", "aim", "want to pay",
    "budget", "about", "roughly", "prefer", "hoping", "looking to spend",
)
_PRIORITY_WORDS = {
    "price": ("price", "cost", "cheap", "cheapest", "money", "affordable", "value", "lowest"),
    "quality": ("quality", "condition", "reliable", "reliability", "durable", "build"),
    "brand": ("brand", "iphone", "apple", "samsung", "pixel", "android", "model"),
    "delivery": ("delivery", "shipping", "fast", "quick", "speed", "timeline", "deadline", "soon"),
    "warranty": ("warranty", "guarantee", "return", "returns"),
    "quantity": ("quantity", "units", "bulk", "volume", "pieces"),
    "battery": ("battery",),
    "support": ("support", "service"),
}


def _extract_amounts(text: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?(?!\s*%)", text.lower()):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        if m.group(2):
            val *= 1000
        out.append(int(round(val)))
    return out


def _update_intake(message: str, goal: dict) -> list[tuple[str, Any]]:
    text = message.lower()
    intake = goal.setdefault(
        "intake", {"target": None, "walk_away": None, "priorities": [], "counterparty": None}
    )
    changed: list[tuple[str, Any]] = []

    if goal.get("kind") == "negotiation":
        has_currency = any(c in text for c in ("$", "usd", "dollar", "eur", "€"))
        amounts = [a for a in _extract_amounts(text) if a >= 50 or has_currency]
        is_walk = any(w in text for w in _WALK_WORDS)
        is_target = any(w in text for w in _TARGET_WORDS)
        for a in amounts:
            if is_walk and intake["walk_away"] is None:
                intake["walk_away"] = a
                changed.append(("walk", a))
            elif is_target and intake["target"] is None:
                intake["target"] = a
                changed.append(("target", a))
            elif intake["target"] is None:
                intake["target"] = a
                changed.append(("target", a))
            elif intake["walk_away"] is None:
                intake["walk_away"] = a
                changed.append(("walk", a))
        if intake["target"] and intake["walk_away"] and intake["target"] > intake["walk_away"]:
            intake["target"], intake["walk_away"] = intake["walk_away"], intake["target"]

    for dim, kws in _PRIORITY_WORDS.items():
        if any(k in text for k in kws) and dim not in intake["priorities"]:
            intake["priorities"].append(dim)
            changed.append(("priority", dim))

    if intake.get("counterparty") is None:
        if any(p in text for p in (
            "find me", "find a", "you find", "source one", "source a", "pick one",
            "whoever", "anyone", "you choose", "you decide", "up to you",
        )):
            intake["counterparty"] = "(agent will source)"
            changed.append(("cp", "find"))
        else:
            m = re.search(r"\b(?:from|with|at|against)\s+([A-Za-z][\w&'’\-. ]{2,40})", message)
            if m:
                cp = m.group(1).strip().rstrip(".")
                intake["counterparty"] = cp
                changed.append(("cp", cp))
    return changed


def _intake_summary(goal: dict | None) -> str:
    if not goal:
        return "nothing yet — still learning what they want"
    it = goal.get("intake", {})
    parts = [f"goal: {goal['title']} ({goal.get('kind', 'negotiation')})"]
    if it.get("target"):
        parts.append(f"target ${it['target']:,}")
    if it.get("walk_away"):
        parts.append(f"walk-away ${it['walk_away']:,}")
    if it.get("priorities"):
        parts.append("priorities: " + ", ".join(it["priorities"]))
    if it.get("counterparty"):
        parts.append(f"counterparty: {it['counterparty']}")
    return "; ".join(parts)


def _sync_constraints(profile: dict, goal: dict | None) -> None:
    if not goal or goal.get("kind") != "negotiation":
        return
    it = goal.get("intake", {})
    parts = []
    if it.get("target"):
        parts.append(f"target ${it['target']:,}")
    if it.get("walk_away"):
        parts.append(f"walk-away ${it['walk_away']:,}")
    if it.get("priorities"):
        parts.append("priorities: " + ", ".join(it["priorities"]))
    if parts:
        profile["constraints"] = ("; ".join(parts))[:300]


def _ack_text(changed: list[tuple[str, Any]], casual: bool) -> str:
    if not changed:
        return ""
    bits = []
    for kind, val in changed:
        if kind == "target":
            bits.append(f"target ~${val:,}")
        elif kind == "walk":
            bits.append(f"ceiling ${val:,}")
        elif kind == "priority":
            bits.append(f"{val} matters")
        elif kind == "cp":
            bits.append("you'll share a link with them" if val == "find" else f"counterparty {val}")
    if not bits:
        return ""
    lead = "Bet" if casual else "Got it"
    return f"{lead} — {', '.join(bits)}. "


def _ask_goal(account_type: str, casual: bool) -> str:
    if account_type == "corporation":
        return (
            "What deal we trying to close? Give me the gist." if casual
            else "What deal are you trying to get done? Give me the gist and what matters most."
        )
    return (
        "What're we doing — buying, selling, leasing, or weighing in on something? Talk to me." if casual
        else "What are you trying to get done — something to buy, sell, lease, or weigh in on? Say it however you'd say it."
    )


def _is_ready(goal: dict | None) -> bool:
    if not goal:
        return False
    it = goal.get("intake", {})
    if goal.get("kind") == "participation":
        return bool(it.get("priorities"))
    return it.get("target") is not None and it.get("walk_away") is not None and bool(it.get("priorities"))


def _statemachine_reply(
    message: str, goal: dict | None, account_type: str, changed: list[tuple[str, Any]], is_new: bool
) -> str:
    casual = _detect_register(message) == "casual"
    if goal is None:
        return _ask_goal(account_type, casual)

    kind = goal.get("kind", "negotiation")
    it = goal.get("intake", {})
    ack = _ack_text(changed, casual)
    if is_new:
        opener = f'Aight, "{goal["title"]}". ' if casual else f'On it — "{goal["title"]}". '
        ack = opener + ack
    nothing_parsed = (not changed) and (not is_new)

    if kind == "participation":
        if not it.get("priorities"):
            q = "where do you stand — what points should I push for?"
        else:
            tail = (
                "i'll spin up your agreed? session so you can share a link and bring the other side in."
                if casual else
                "I'll set up your agreed? session — share the link to bring the other side in."
            )
            return (ack + f"Got your position. {tail[0].upper() + tail[1:]}").strip()
    else:
        t, w, pr = it.get("target"), it.get("walk_away"), it.get("priorities")
        if t is None and w is None:
            q = "what's your ideal price, and the most you'd pay?"
        elif w is None:
            q = "what's the most you'd pay — your walk-away?"
        elif t is None:
            q = "what price are you hoping for?"
        elif not pr:
            q = "besides price, what matters — brand, condition, delivery, quantity?"
        else:
            tail = (
                "i'll spin up your agreed? session — you just send the link to the seller to kick it off."
                if casual else
                "I'll set up your agreed? session — share the link with the seller to start the negotiation."
            )
            return (ack + f"That's what I needed. {tail[0].upper() + tail[1:]}").strip()

    q = q[0].upper() + q[1:]
    if nothing_parsed:
        lead = "Hmm, missed that — " if casual else "Didn't quite catch that — "
        return (lead + q[0].lower() + q[1:]).strip()
    return (ack + q).strip()


def _suggested_questions(goal: dict | None, account_type: str) -> list[str]:
    """Concrete, first-person quick replies for the next step (tap to prefill)."""
    if goal is None:
        if account_type == "corporation":
            return ["We need a supply contract", "Renew a vendor deal", "Hire a contractor"]
        return ["I want to buy something", "I want to sell something", "I want a say in a decision"]

    kind = goal.get("kind", "negotiation")
    it = goal.get("intake", {})
    if kind == "participation":
        if not it.get("priorities"):
            return ["My main concern is…", "I care most about…", "I'd compromise on…"]
        return ["Set it up", "Add a tentative point", "Let me add another stance"]

    t, w, pr = it.get("target"), it.get("walk_away"), it.get("priorities")
    if t is None and w is None:
        return ["My budget is around $…", "Most I'd pay is $…", "I'm hoping for $…"]
    if w is None:
        return ["Most I'd pay is $…", "My hard limit is $…"]
    if t is None:
        return ["I'm hoping for around $…"]
    if not pr:
        return ["Price matters most", "Condition & brand matter", "Just the lowest price"]
    return ["Set up the agreed? session", "Add another priority"]


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
