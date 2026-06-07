"""Route inbound SMS/voice into the same chat agent used on the web."""

from __future__ import annotations

import html
import re

from ..persistence.store import UserScopedStore
from .phone_registry import lookup_user


def _load_profile(st: UserScopedStore):
    from ..api.chat_service import _default_profile, chat_with_agent

    prof_rec = next((r for r in st.list("user_profile")), None)
    profile = prof_rec["data"] if prof_rec else _default_profile()
    chat_rec = next((r for r in st.list("chat_history")), None)
    history = chat_rec["data"] if chat_rec else []
    return prof_rec, chat_rec, profile, history, chat_with_agent


def handle_inbound_sms(from_phone: str, body: str) -> str:
    """Process inbound SMS; returns TwiML or empty string (for MessagingResponse)."""
    user_id = lookup_user(from_phone)
    if not user_id:
        return "Thanks for texting agreed — set up your phone in the web app first so I know it's you."

    st = UserScopedStore(user_id)
    prof_rec, chat_rec, profile, history, chat_with_agent = _load_profile(st)
    message = (body or "").strip() or "Hey"
    result = chat_with_agent(message, history, profile)
    history = [
        *history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": result["reply"]},
    ]
    st.put("user_profile", result["profile"], record_id=prof_rec["id"] if prof_rec else None)
    st.put("chat_history", history, record_id=chat_rec["id"] if chat_rec else None)

    from .followups import maybe_schedule_followup

    maybe_schedule_followup(st, result["profile"], result)
    return result["reply"]


def handle_voice_turn(user_id: str, speech: str) -> str:
    """Process a speech turn on a Twilio call; returns spoken reply text."""
    st = UserScopedStore(user_id)
    prof_rec, chat_rec, profile, history, chat_with_agent = _load_profile(st)
    message = (speech or "").strip() or "I'm listening."
    result = chat_with_agent(message, history, profile)
    history = [
        *history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": result["reply"]},
    ]
    st.put("user_profile", result["profile"], record_id=prof_rec["id"] if prof_rec else None)
    st.put("chat_history", history, record_id=chat_rec["id"] if chat_rec else None)
    reply = result["reply"].strip()
    reply = re.sub(r"\s+", " ", reply)
    return reply[:500] if reply else "Got it. Anything else I should know?"


def voice_twiml(user_id: str, purpose: str = "", speech: str | None = None) -> str:
    """Build TwiML for outbound/inbound voice loops."""
    base = purpose.strip()
    gather_url = f"/webhooks/twilio/voice/gather?user_id={html.escape(user_id, quote=True)}"

    if speech is not None:
        reply = handle_voice_turn(user_id, speech)
        say = html.escape(reply)
        prompt = html.escape(base or "What else should I know?")
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{say}</Say>
  <Gather input="speech" action="{gather_url}" method="POST" speechTimeout="auto" timeout="5">
    <Say>{prompt}</Say>
  </Gather>
  <Say>Text me anytime, or hop back on the app. Talk soon.</Say>
</Response>"""

    opener = html.escape(
        base
        or "Hi, it's your agreed agent. I had a quick follow-up based on our last chat."
    )
    question = html.escape(
        base if base.endswith("?") else "What's the most important thing for me to know right now?"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{opener}</Say>
  <Gather input="speech" action="{gather_url}" method="POST" speechTimeout="auto" timeout="6">
    <Say>{question}</Say>
  </Gather>
  <Say>Didn't catch that — feel free to text me back.</Say>
</Response>"""


def sms_twiml_reply(body: str) -> str:
    """Minimal TwiML for SMS auto-reply (Twilio accepts plain text too)."""
    return body[:1600]
