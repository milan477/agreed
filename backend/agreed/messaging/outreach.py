"""Unified outbound messaging — Twilio in production, iMessage on macOS."""

from __future__ import annotations

from ..config import get_settings
from ..observability import op
from .imessage import draft_message, send_imessage, start_facetime
from .twilio_client import normalize_phone, send_sms, start_call, twilio_configured


def public_base_url() -> str:
    return get_settings().public_base_url.rstrip("/")


@op(name="outreach.send_text", kind="tool")
def send_text(recipient: str, body: str, *, voice_sample: str = "") -> dict:
    recipient = (recipient or "").strip()
    body = (body or "").strip()
    if not recipient or not body:
        return {"sent": False, "error": "Recipient and message are required."}

    if twilio_configured() and normalize_phone(recipient):
        return send_sms(recipient, body)
    return send_imessage(recipient, body)


@op(name="outreach.start_call", kind="tool")
def start_outbound_call(recipient: str, user_id: str, purpose: str = "") -> dict:
    recipient = (recipient or "").strip()
    if not recipient:
        return {"started": False, "error": "Recipient is required."}

    if twilio_configured() and normalize_phone(recipient):
        base = public_base_url()
        if not base:
            return {"started": False, "error": "PUBLIC_BASE_URL is required for Twilio voice webhooks."}
        q = f"user_id={user_id}"
        if purpose:
            from urllib.parse import quote

            q += f"&purpose={quote(purpose[:200])}"
        url = f"{base}/webhooks/twilio/voice?{q}"
        return start_call(recipient, url)
    return start_facetime(recipient)


@op(name="outreach.draft", kind="agent")
def draft_outbound(recipient: str, purpose: str, voice_sample: str = "", channel: str = "text") -> str:
    return draft_message(recipient, purpose, voice_sample=voice_sample, channel=channel)
