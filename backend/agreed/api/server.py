"""FastAPI app — the platform's HTTP surface for the CopilotKit UI.

Auth is a simple `X-User-Id` header for the demo; every data operation is scoped
to that user via `UserScopedStore`, so isolation holds regardless of the caller.
"""

from __future__ import annotations

import threading
import time
import uuid

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from ..agents.negotiator import StrategyParams
from ..agents.representation import RepresentationAgent
from ..agents.self_improve import SelfImprovementAgent
from ..config import capability_report, cors_origin_list
from ..domain.frameworks import FRAMEWORKS
from ..domain.term_sheets import DIM_LABELS, get_scenario
from ..evals.evaluations import run_eval_suite
from ..observability import init_observability, weave_trace_url
from ..orchestration.graph import NegotiationOrchestrator
from ..persistence.conversations import (
    create_conversation,
    get_conversation,
    list_conversations,
    resolve_active_conversation,
    save_messages,
    title_from_first_message,
)
from ..persistence.store import UserScopedStore, ensure_user, init_db
from .chat_service import (
    _default_profile,
    add_tentative_agreement,
    chat_with_agent,
    confirm_agent_choice,
    connect_source,
    join_via_invite,
    list_contacts,
    list_user_sessions,
    new_session_from_goal,
    prepare_session,
    save_probe,
    set_account_type,
    set_tentative_status,
    submit_agent,
    update_contact_info,
)
from ..integrations.connectors import list_connectors
from ..messaging.channel_router import handle_inbound_sms, voice_twiml
from ..messaging.followups import list_followups, maybe_schedule_followup, process_all_due_followups, schedule_followup
from ..messaging.outreach import draft_outbound, send_text, start_outbound_call
from .schemas import (
    AccountTypeIn,
    AgentChoiceIn,
    ApproveIn,
    BriefIn,
    ChatIn,
    ContactIn,
    ContactInfoIn,
    FollowupScheduleIn,
    JoinInviteIn,
    MessageDraftIn,
    MessageSendIn,
    NegotiationIn,
    OnboardingIn,
    ProbeIn,
    SelfImproveIn,
    SessionCreateIn,
    SessionUpdateIn,
    SignIn,
    StrategyIn,
    TentativeIn,
    TentativeStatusIn,
    UserIn,
)
from ..persistence.sessions import get_session, update_session
from ..memory.store import long_term, short_term
from .summary import summarize_trace

app = FastAPI(title="agreed", description="better agreements, faster", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    init_observability()

    def _followup_worker() -> None:
        while True:
            time.sleep(60)
            try:
                process_all_due_followups()
            except Exception:
                pass

    threading.Thread(target=_followup_worker, daemon=True).start()


def current_user(x_user_id: str | None = Header(default=None)) -> str:
    """Resolve the authenticated user. Creates a demo user if none supplied."""
    uid = x_user_id or "demo-user"
    ensure_user(uid)
    return uid


def store(user_id: str = Depends(current_user)) -> UserScopedStore:
    return UserScopedStore(user_id=user_id)


def _strategy(s: StrategyIn | None) -> StrategyParams | None:
    if s is None:
        return None
    base = StrategyParams()
    return StrategyParams(
        concession_rate=s.concession_rate if s.concession_rate is not None else base.concession_rate,
        acceptance_threshold=s.acceptance_threshold if s.acceptance_threshold is not None else base.acceptance_threshold,
        threshold_decay=s.threshold_decay if s.threshold_decay is not None else base.threshold_decay,
        anchor_aggressiveness=s.anchor_aggressiveness if s.anchor_aggressiveness is not None else base.anchor_aggressiveness,
        prompt_addendum=s.prompt_addendum or "",
    )


# ── meta ──────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "capabilities": capability_report(), "weave_url": weave_trace_url()}


@app.get("/api/frameworks")
def frameworks() -> dict:
    return {"frameworks": [{"key": f.key, "name": f.name, "description": f.description} for f in FRAMEWORKS.values()]}


@app.get("/api/scenario")
def scenario() -> dict:
    sc = get_scenario()
    return {
        "key": sc.key,
        "title": sc.title,
        "description": sc.description,
        "dimensions": [{"key": d, "label": DIM_LABELS.get(d, d)} for d in sc.dimensions],
    }


@app.post("/api/users")
def create_user(body: UserIn) -> dict:
    uid = uuid.uuid4().hex[:12]
    ensure_user(uid, body.email, body.name)
    return {"user_id": uid, "email": body.email, "name": body.name}


# ── step 1: onboarding ────────────────────────────────────────────────────────
@app.get("/api/onboarding/questions")
def onboarding_questions() -> dict:
    return {"questions": RepresentationAgent(get_scenario()).questions()}


@app.post("/api/onboarding/profile")
def onboarding_profile(body: OnboardingIn, st: UserScopedStore = Depends(store)) -> dict:
    rep = RepresentationAgent(get_scenario())
    profile = rep.build_profile(body.party, body.purpose, body.answers)
    rid = st.put("profile", profile)
    return {"profile_id": rid, "profile": profile}


@app.post("/api/profile/approve")
def approve_profile(body: ApproveIn, st: UserScopedStore = Depends(store)) -> dict:
    rec = st.get(body.record_id)
    if not rec:
        raise HTTPException(404, "profile not found")
    data = rec["data"]
    data["approved"] = True
    st.put(rec["kind"], data, record_id=body.record_id)
    return {"approved": True, "record_id": body.record_id}


# ── step 2.5: brief ───────────────────────────────────────────────────────────
@app.post("/api/brief")
def build_brief(body: BriefIn, st: UserScopedStore = Depends(store)) -> dict:
    profile = st.get(body.profile_id)
    if not profile:
        raise HTTPException(404, "profile not found")
    rep = RepresentationAgent(get_scenario())
    brief = rep.build_brief(body.party, profile["data"], self_improved=body.self_improved)
    rid = st.put("brief", brief, ref=body.profile_id)
    return {"brief_id": rid, "brief": brief}


# ── step 3-4: negotiation ─────────────────────────────────────────────────────
@app.post("/api/negotiation/run")
def run_negotiation(body: NegotiationIn, st: UserScopedStore = Depends(store)) -> dict:
    init_observability()
    orch = NegotiationOrchestrator(
        framework=body.framework,
        max_rounds=body.max_rounds,
        use_moderator=body.use_moderator,
        buyer_strategy=_strategy(body.buyer_strategy),
        seller_strategy=_strategy(body.seller_strategy),
    )
    result = orch.run()
    payload = result.to_dict()
    rid = st.put("negotiation", payload, ref=result.trace_id)
    payload["negotiation_id"] = rid
    return payload


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> dict:
    return summarize_trace(trace_id)


# ── self-improvement ──────────────────────────────────────────────────────────
@app.post("/api/self-improve")
def self_improve(body: SelfImproveIn) -> dict:
    init_observability()
    agent = SelfImprovementAgent()
    diagnosis = agent.read_traces()
    opt = agent.optimize_strategy(body.party, framework=body.framework, metric=body.metric)
    opt.pop("strategy", None)  # not JSON-serializable; the dict form is included
    return {"diagnosis": diagnosis, "optimization": opt}


@app.get("/api/evals")
def evals(framework: str = "pareto", n: int = 5) -> dict:
    init_observability()
    return run_eval_suite(framework=framework, n=n).to_dict()


# ── step 5: signing ───────────────────────────────────────────────────────────
@app.post("/api/agreement/sign")
def sign(body: SignIn, st: UserScopedStore = Depends(store)) -> dict:
    neg = st.get(body.negotiation_id)
    if not neg:
        raise HTTPException(404, "negotiation not found")
    agreement = {
        "negotiation_id": body.negotiation_id,
        "terms": neg["data"].get("deal_terms"),
        "signatures": {body.party: body.signature},
        "bound": False,  # binds only when both parties sign
    }
    rid = st.put("agreement", agreement, ref=body.negotiation_id)
    return {"agreement_id": rid, "agreement": agreement}


# ── data + audit ──────────────────────────────────────────────────────────────
@app.get("/api/records")
def records(kind: str | None = None, st: UserScopedStore = Depends(store)) -> dict:
    return {"records": st.list(kind)}


@app.get("/api/audit")
def audit(st: UserScopedStore = Depends(store)) -> dict:
    return {"audit_log": st.audit_trail()}


def _profile_bundle(st: UserScopedStore) -> tuple[dict | None, dict]:
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    return prof_rec, profile


def _legacy_chat_messages(st: UserScopedStore) -> list[dict]:
    chat_rec = next((r for r in st.list("chat_history")), None)
    return chat_rec["data"] if chat_rec else []


# ── home: chat + opportunities ────────────────────────────────────────────────
@app.get("/api/home")
def home(user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    prof_rec, profile = _profile_bundle(st)
    legacy = _legacy_chat_messages(st)
    conv = resolve_active_conversation(st.user_id, profile, legacy_messages=legacy)
    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    sessions = list_user_sessions(st)
    goals = profile.get("goals", [])
    return {
        "user_id": user_id,
        "profile": profile,
        "chat_history": conv["messages"],
        "active_conversation_id": conv["conversation_id"],
        "conversations": list_conversations(st.user_id),
        "goals": goals,
        "sessions": sessions,
        "contacts": list_contacts(st),
        "followups": list_followups(st),
    }


@app.get("/api/conversations")
def conversations_list(st: UserScopedStore = Depends(store)) -> dict:
    return {"conversations": list_conversations(st.user_id)}


@app.post("/api/conversations")
def conversations_create(st: UserScopedStore = Depends(store)) -> dict:
    prof_rec, profile = _profile_bundle(st)
    conv = create_conversation(st.user_id)
    profile["active_conversation_id"] = conv["conversation_id"]
    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    return {"conversation": conv}


@app.get("/api/conversations/{conversation_id}")
def conversations_get(conversation_id: str, st: UserScopedStore = Depends(store)) -> dict:
    conv = get_conversation(st.user_id, conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {"conversation": conv}


@app.post("/api/conversations/{conversation_id}/activate")
def conversations_activate(conversation_id: str, st: UserScopedStore = Depends(store)) -> dict:
    conv = get_conversation(st.user_id, conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    prof_rec, profile = _profile_bundle(st)
    profile["active_conversation_id"] = conversation_id
    st.put("user_profile", profile, record_id=prof_rec["id"] if prof_rec else None)
    return {"conversation": conv, "profile": profile}


@app.post("/api/chat")
def chat(body: ChatIn, st: UserScopedStore = Depends(store)) -> dict:
    prof_rec, profile = _profile_bundle(st)
    legacy = _legacy_chat_messages(st) if not body.conversation_id else []
    conv = resolve_active_conversation(
        st.user_id,
        profile,
        conversation_id=body.conversation_id,
        legacy_messages=legacy,
    )
    history = body.history if body.history else conv["messages"]
    memories = long_term().recall(st.user_id, body.message, limit=5)
    if memories:
        profile = {**profile, "recalled_memories": memories}
    result = chat_with_agent(body.message, history, profile)
    history = [*history, {"role": "user", "content": body.message}, {"role": "assistant", "content": result["reply"]}]
    title = title_from_first_message(body.message) if not conv["messages"] else None
    save_messages(st.user_id, conv["conversation_id"], history, title=title)
    updated_profile = {**result["profile"], "active_conversation_id": conv["conversation_id"]}
    st.put("user_profile", updated_profile, record_id=prof_rec["id"] if prof_rec else None)
    if len(body.message.strip()) >= 12:
        long_term().remember(st.user_id, body.message.strip()[:240], {"source": "chat"})
    short_term().set(st.user_id, "last_chat", {"message": body.message, "reply": result["reply"]}, ttl=7200)
    followup = maybe_schedule_followup(st, updated_profile, result)
    return {**result, "profile": updated_profile, "conversation_id": conv["conversation_id"], "followup_scheduled": followup}


@app.post("/api/invitations/join")
def join_invitation(body: JoinInviteIn, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = join_via_invite(user_id, body.link, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session, "invite_url": f"/join/{session['invite_code']}"}


@app.post("/api/sessions")
def create_session(body: SessionCreateIn, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    goal = {"id": body.goal_id or uuid.uuid4().hex[:10], "title": body.title, "kind": body.kind}
    if body.other_party_label:
        goal["other_party_label"] = body.other_party_label
    session = new_session_from_goal(user_id, goal, st)
    return {"session": session, "invite_url": f"/join/{session['invite_code']}"}


@app.get("/api/sessions/{session_id}")
def get_session_detail(session_id: str, st: UserScopedStore = Depends(store)) -> dict:
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    return {"session": session, "contacts": list_contacts(st)}


@app.patch("/api/sessions/{session_id}")
def patch_session(session_id: str, body: SessionUpdateIn, st: UserScopedStore = Depends(store)) -> dict:
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    for field in ("other_party_id", "other_party_label", "framework", "max_rounds", "use_custom_agent", "custom_agent_url", "status"):
        val = getattr(body, field, None)
        if val is not None:
            session[field] = val
    if body.other_party_id and body.other_party_label:
        st.put("contact", {"user_id": body.other_party_id, "label": body.other_party_label})
    session = update_session(session_id, session)
    return {"session": session}


@app.post("/api/sessions/{session_id}/agent-choice")
def session_agent_choice(
    session_id: str,
    body: AgentChoiceIn,
    user_id: str = Depends(current_user),
    st: UserScopedStore = Depends(store),
) -> dict:
    """Choose platform vs external agent, then automatically run preparation."""
    try:
        session = confirm_agent_choice(
            session_id,
            user_id,
            st,
            use_custom_agent=body.use_custom_agent,
            custom_agent_url=body.custom_agent_url,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}


@app.post("/api/sessions/{session_id}/probe")
def session_probe(
    session_id: str,
    body: ProbeIn,
    user_id: str = Depends(current_user),
    st: UserScopedStore = Depends(store),
) -> dict:
    """Save the targets/viewpoints the agent probed for, then build the brief."""
    try:
        session = save_probe(
            session_id,
            user_id,
            st,
            targets=body.targets,
            viewpoints=body.viewpoints,
            interaction_mode=body.interaction_mode,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}


@app.post("/api/sessions/{session_id}/prepare")
def session_prepare(session_id: str, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = prepare_session(session_id, user_id, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}


@app.post("/api/account-type")
def account_type(body: AccountTypeIn, st: UserScopedStore = Depends(store)) -> dict:
    profile = set_account_type(body.account_type, st)
    return {"profile": profile}


# ── connectors: the agent learns about the user ───────────────────────────────
@app.get("/api/connectors")
def connectors(st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    connected = (prof_rec["data"].get("connections", []) if prof_rec else [])
    return {"connectors": list_connectors(), "connected": connected}


@app.post("/api/connectors/{source_id}/connect")
def connect_connector(source_id: str, st: UserScopedStore = Depends(store)) -> dict:
    try:
        return connect_source(source_id, st)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── messaging: the agent texts / calls on the user's behalf ───────────────────
@app.patch("/api/profile/contact")
def profile_contact(body: ContactInfoIn, st: UserScopedStore = Depends(store)) -> dict:
    profile = update_contact_info(
        st,
        phone=body.phone,
        email=body.email,
        preferred_channel=body.preferred_channel,
        outreach_enabled=body.outreach_enabled,
        followup_delay_minutes=body.followup_delay_minutes,
    )
    return {"profile": profile}


@app.get("/api/followups")
def followups(st: UserScopedStore = Depends(store)) -> dict:
    return {"followups": list_followups(st)}


@app.post("/api/followups/schedule")
def followup_schedule(body: FollowupScheduleIn, st: UserScopedStore = Depends(store)) -> dict:
    item = schedule_followup(
        st,
        channel=body.channel,
        purpose=body.purpose,
        delay_minutes=body.delay_minutes,
        open_question=body.open_question or body.purpose,
    )
    return {"followup": item}


@app.post("/api/followups/process")
def followup_process(st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    from ..messaging.followups import process_user_followups

    sent = process_user_followups(st, profile)
    return {"sent": sent}


@app.post("/api/message/draft")
def message_draft(body: MessageDraftIn, st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    voice = (prof_rec["data"].get("voice_sample", "") if prof_rec else "")
    text = draft_outbound(body.recipient, body.purpose, voice_sample=voice, channel=body.channel)
    return {"draft": text}


@app.post("/api/message/send")
def message_send(body: MessageSendIn, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    voice = prof_rec["data"].get("voice_sample", "") if prof_rec else ""
    if body.channel == "call":
        return start_outbound_call(body.recipient, user_id, purpose=body.body or "Quick check-in from your agreed agent.")
    return send_text(body.recipient, body.body, voice_sample=voice)


# ── Twilio webhooks (inbound SMS + voice) ─────────────────────────────────────
@app.post("/webhooks/twilio/sms")
async def twilio_sms_webhook(
    From: str = Form(default=""),
    Body: str = Form(default=""),
) -> Response:
    reply = handle_inbound_sms(From, Body)
    try:
        from twilio.twiml.messaging_response import MessagingResponse

        resp = MessagingResponse()
        resp.message(reply)
        return Response(content=str(resp), media_type="application/xml")
    except Exception:
        return Response(content=reply, media_type="text/plain")


@app.post("/webhooks/twilio/voice")
def twilio_voice_webhook(
    user_id: str = Query(default=""),
    purpose: str = Query(default=""),
) -> Response:
    if not user_id:
        twiml = """<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, this line is not configured.</Say></Response>"""
        return Response(content=twiml, media_type="application/xml")
    return Response(content=voice_twiml(user_id, purpose=purpose), media_type="application/xml")


@app.post("/webhooks/twilio/voice/gather")
def twilio_voice_gather(
    user_id: str = Query(default=""),
    SpeechResult: str = Form(default=""),
    purpose: str = Query(default=""),
) -> Response:
    if not user_id:
        twiml = """<?xml version="1.0" encoding="UTF-8"?><Response><Say>Goodbye.</Say></Response>"""
        return Response(content=twiml, media_type="application/xml")
    return Response(content=voice_twiml(user_id, purpose=purpose, speech=SpeechResult), media_type="application/xml")


# ── tentative agreements ──────────────────────────────────────────────────────
@app.post("/api/sessions/{session_id}/tentative")
def add_tentative(session_id: str, body: TentativeIn, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = add_tentative_agreement(session_id, user_id, body.text, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}


@app.patch("/api/sessions/{session_id}/tentative")
def update_tentative(session_id: str, body: TentativeStatusIn, st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = set_tentative_status(session_id, body.item_id, body.status, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}


@app.post("/api/sessions/{session_id}/submit")
def submit_session_agent(session_id: str, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = submit_agent(session_id, user_id, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}
