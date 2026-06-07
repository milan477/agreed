"""FastAPI app — the platform's HTTP surface for the CopilotKit UI.

Auth is a simple `X-User-Id` header for the demo; every data operation is scoped
to that user via `UserScopedStore`, so isolation holds regardless of the caller.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..agents.negotiator import StrategyParams
from ..agents.representation import RepresentationAgent
from ..agents.self_improve import SelfImprovementAgent
from ..config import capability_report
from ..domain.frameworks import FRAMEWORKS
from ..domain.term_sheets import DIM_LABELS, get_scenario
from ..evals.evaluations import run_eval_suite
from ..observability import init_observability, weave_trace_url
from ..orchestration.graph import NegotiationOrchestrator
from ..persistence.store import UserScopedStore, ensure_user, init_db
from .chat_service import (
    _default_profile,
    chat_with_agent,
    join_via_invite,
    list_contacts,
    list_user_sessions,
    new_session_from_goal,
    submit_agent,
)
from .schemas import (
    ApproveIn,
    BriefIn,
    ChatIn,
    ContactIn,
    JoinInviteIn,
    NegotiationIn,
    OnboardingIn,
    SelfImproveIn,
    SessionCreateIn,
    SessionUpdateIn,
    SignIn,
    StrategyIn,
    UserIn,
)
from ..persistence.sessions import get_session, update_session
from .summary import summarize_trace

app = FastAPI(title="agreed", description="better agreements, faster", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    init_observability()


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


# ── home: chat + opportunities ────────────────────────────────────────────────
@app.get("/api/home")
def home(user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    chat_rec = next((r for r in st.list("chat_history")), None)
    history = chat_rec["data"] if chat_rec else []
    sessions = list_user_sessions(st)
    goals = profile.get("goals", [])
    return {
        "user_id": user_id,
        "profile": profile,
        "chat_history": history,
        "goals": goals,
        "sessions": sessions,
        "contacts": list_contacts(st),
    }


@app.post("/api/chat")
def chat(body: ChatIn, st: UserScopedStore = Depends(store)) -> dict:
    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    chat_rec = next((r for r in st.list("chat_history")), None)
    history = body.history if body.history else (chat_rec["data"] if chat_rec else [])
    result = chat_with_agent(body.message, history, profile)
    history = [*history, {"role": "user", "content": body.message}, {"role": "assistant", "content": result["reply"]}]
    pid = prof_rec["id"] if prof_rec else None
    cid = chat_rec["id"] if chat_rec else None
    st.put("user_profile", result["profile"], record_id=pid)
    st.put("chat_history", history, record_id=cid)
    return result


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


@app.post("/api/sessions/{session_id}/submit")
def submit_session_agent(session_id: str, user_id: str = Depends(current_user), st: UserScopedStore = Depends(store)) -> dict:
    try:
        session = submit_agent(session_id, user_id, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"session": session}
