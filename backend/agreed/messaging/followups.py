"""Automatic follow-up texts/calls when the agent needs more information."""

from __future__ import annotations

import time
import uuid

from ..observability import op, record_event
from ..persistence.store import UserScopedStore
from .outreach import draft_outbound, public_base_url, send_text, start_outbound_call
from .twilio_client import twilio_configured


def _pending_followups(st: UserScopedStore) -> list[dict]:
    return [r for r in st.list("followup") if r["data"].get("status") == "pending"]


@op(name="followups.schedule", kind="tool")
def schedule_followup(
    st: UserScopedStore,
    *,
    channel: str,
    purpose: str,
    delay_minutes: float = 2,
    open_question: str = "",
) -> dict:
    channel = channel if channel in ("text", "call", "auto") else "text"
    now = time.time()
    payload = {
        "id": uuid.uuid4().hex[:12],
        "channel": channel,
        "purpose": purpose[:400],
        "open_question": open_question[:400],
        "scheduled_at": now + max(delay_minutes, 0) * 60,
        "status": "pending",
        "created_at": now,
    }
    rid = st.put("followup", payload, record_id=payload["id"])
    record_event("followup_scheduled", kind="tool", channel=channel, id=rid)
    return payload


def maybe_schedule_followup(st: UserScopedStore, profile: dict, chat_result: dict) -> dict | None:
    """After web chat, queue an outbound follow-up if the agent asked a question."""
    if profile.get("outreach_enabled") is False:
        return None
    phone = (profile.get("phone") or "").strip()
    if not phone:
        return None
    if _pending_followups(st):
        return None

    reply = (chat_result.get("reply") or "").strip()
    if "?" not in reply:
        return None

    channel = profile.get("preferred_channel") or "text"
    if channel == "auto":
        channel = "call" if twilio_configured() and public_base_url() else "text"

    delay = float(profile.get("followup_delay_minutes") or 2)
    return schedule_followup(
        st,
        channel=channel,
        purpose=reply,
        open_question=reply,
        delay_minutes=delay,
    )


@op(name="followups.process_user", kind="tool")
def process_user_followups(st: UserScopedStore, profile: dict) -> list[dict]:
    """Send due follow-ups for one user."""
    phone = (profile.get("phone") or "").strip()
    if not phone:
        return []

    voice = profile.get("voice_sample", "")
    results: list[dict] = []
    now = time.time()

    for rec in st.list("followup"):
        data = rec["data"]
        if data.get("status") != "pending":
            continue
        if data.get("scheduled_at", 0) > now:
            continue

        channel = data.get("channel") or "text"
        if channel == "auto":
            channel = "call" if twilio_configured() and public_base_url() else "text"

        purpose = data.get("open_question") or data.get("purpose") or "Quick follow-up from your agreed agent."
        outcome: dict

        if channel == "call":
            outcome = start_outbound_call(phone, st.user_id, purpose=purpose)
            data["status"] = "sent" if outcome.get("started") else "failed"
            data["result"] = outcome
        else:
            body = draft_outbound(phone, purpose, voice_sample=voice, channel="text")
            outcome = send_text(phone, body, voice_sample=voice)
            data["status"] = "sent" if outcome.get("sent") else "failed"
            data["result"] = outcome
            data["body"] = body

        data["sent_at"] = now
        st.put("followup", data, record_id=rec["id"])
        results.append({"followup_id": rec["id"], **data})
        record_event("followup_sent", kind="tool", channel=channel, status=data["status"])

    return results


def list_followups(st: UserScopedStore) -> list[dict]:
    return [r["data"] for r in st.list("followup")]


def process_all_due_followups() -> int:
    """Background job: send due follow-ups for every user."""
    from ..api.chat_service import _default_profile
    from ..persistence.db import _adapt_sql, _conn, _lock, init_db

    init_db()
    with _lock, _conn() as conn:
        rows = conn.execute(
            _adapt_sql("SELECT DISTINCT user_id FROM records WHERE kind=%s"),
            ("followup",),
        ).fetchall()

    sent = 0
    for row in rows:
        uid = row["user_id"]
        st = UserScopedStore(uid)
        prof_rec = next((r for r in st.list("user_profile")), None)
        profile = prof_rec["data"] if prof_rec else _default_profile()
        sent += len(process_user_followups(st, profile))
    return sent
