"""Twilio SMS + programmable voice for outbound/inbound agent reach-out."""

from __future__ import annotations

import re

from ..config import get_settings
from ..observability import op, record_event


def twilio_configured() -> bool:
    s = get_settings()
    return bool(s.twilio_sid and s.twilio_token and s.twilio_from)


def normalize_phone(raw: str, default_country: str = "1") -> str:
    """Best-effort E.164 normalization for US-centric demo numbers."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        digits = "+" + re.sub(r"\D", "", raw[1:])
        return digits if len(digits) >= 8 else ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+{default_country}{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return raw


@op(name="twilio.send_sms", kind="tool")
def send_sms(to: str, body: str) -> dict:
    to = normalize_phone(to)
    body = (body or "").strip()
    if not to or not body:
        return {"sent": False, "error": "Phone number and message are required."}
    if not twilio_configured():
        return {"sent": False, "simulated": True, "to": to, "body": body, "note": "Twilio not configured."}

    try:
        from twilio.rest import Client

        s = get_settings()
        client = Client(s.twilio_sid, s.twilio_token)
        msg = client.messages.create(to=to, from_=s.twilio_from, body=body[:1600])
        record_event("twilio_sms_sent", kind="tool", to=to, sid=msg.sid)
        return {"sent": True, "simulated": False, "to": to, "body": body, "sid": msg.sid}
    except Exception as exc:
        record_event("twilio_sms_failed", kind="tool", to=to, error=str(exc))
        return {"sent": False, "error": str(exc), "to": to, "body": body}


@op(name="twilio.start_call", kind="tool")
def start_call(to: str, twiml_url: str) -> dict:
    to = normalize_phone(to)
    if not to:
        return {"started": False, "error": "Phone number is required."}
    if not twilio_configured():
        return {"started": False, "simulated": True, "to": to, "note": "Twilio not configured."}

    try:
        from twilio.rest import Client

        s = get_settings()
        client = Client(s.twilio_sid, s.twilio_token)
        call = client.calls.create(to=to, from_=s.twilio_from, url=twiml_url, method="POST")
        record_event("twilio_call_started", kind="tool", to=to, sid=call.sid)
        return {"started": True, "simulated": False, "to": to, "sid": call.sid}
    except Exception as exc:
        record_event("twilio_call_failed", kind="tool", to=to, error=str(exc))
        return {"started": False, "error": str(exc), "to": to}
