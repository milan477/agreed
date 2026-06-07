"""Send iMessages / start FaceTime via macOS automation.

On macOS the agent can genuinely send an iMessage through the Messages app using
AppleScript (`osascript`). This needs Automation permission for the host process
(System Settings → Privacy & Security → Automation). On non-macOS hosts, or when
permission/Messages isn't available, the call degrades gracefully and reports a
simulated send so the demo flow never breaks.
"""

from __future__ import annotations

import platform
import shlex
import subprocess

from ..llm import chat_text, llm_available
from ..observability import op

IS_MAC = platform.system() == "Darwin"


def _osascript(script: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, (proc.stderr.strip() or "osascript failed")
    except FileNotFoundError:
        return False, "osascript not available (non-macOS host)"
    except subprocess.TimeoutExpired:
        return False, "Messages timed out"
    except Exception as e:  # pragma: no cover - defensive
        return False, str(e)


@op(name="messaging.imessage_send", kind="tool")
def send_imessage(recipient: str, body: str) -> dict:
    """Send an iMessage to a phone number / Apple ID / contact handle."""
    recipient = (recipient or "").strip()
    body = (body or "").strip()
    if not recipient or not body:
        return {"sent": False, "simulated": False, "error": "Recipient and message are required."}

    if not IS_MAC:
        return {"sent": True, "simulated": True, "recipient": recipient, "body": body,
                "note": "Simulated send (host is not macOS)."}

    script = (
        'on run {targetBuddyPhone, targetMessage}\n'
        '  tell application "Messages"\n'
        '    set targetService to 1st account whose service type = iMessage\n'
        '    set targetBuddy to participant targetBuddyPhone of targetService\n'
        '    send targetMessage to targetBuddy\n'
        '  end tell\n'
        'end run'
    )
    # Pass args safely via osascript positional args
    try:
        proc = subprocess.run(
            ["osascript", "-e", script, recipient, body],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            return {"sent": True, "simulated": False, "recipient": recipient, "body": body}
        return {"sent": False, "simulated": False, "recipient": recipient, "body": body,
                "error": proc.stderr.strip() or "Messages refused the send (check Automation permission)."}
    except FileNotFoundError:
        return {"sent": True, "simulated": True, "recipient": recipient, "body": body,
                "note": "Simulated send (osascript missing)."}
    except Exception as e:
        return {"sent": False, "simulated": False, "error": str(e)}


@op(name="messaging.facetime", kind="tool")
def start_facetime(recipient: str) -> dict:
    """Open a FaceTime call to the recipient (macOS)."""
    recipient = (recipient or "").strip()
    if not recipient:
        return {"started": False, "error": "Recipient is required."}
    if not IS_MAC:
        return {"started": True, "simulated": True, "recipient": recipient,
                "note": "Simulated call (host is not macOS)."}
    ok, out = _osascript(f'open location "facetime://{shlex.quote(recipient).strip(chr(39))}"')
    if ok:
        return {"started": True, "simulated": False, "recipient": recipient}
    return {"started": False, "simulated": False, "recipient": recipient, "error": out}


@op(name="messaging.draft", kind="agent")
def draft_message(recipient: str, purpose: str, voice_sample: str = "", channel: str = "text") -> str:
    """Draft an outbound message in the user's own voice."""
    if llm_available():
        voice = f"Match this person's voice/tone exactly: \"{voice_sample}\".\n" if voice_sample else ""
        sys = (
            "You draft a short outbound " + ("text message" if channel == "text" else "message") +
            " on behalf of a person, in THEIR voice. 1-2 sentences, natural, no signature. " + voice
        )
        usr = f"Recipient: {recipient or 'the other party'}.\nPurpose: {purpose}.\nWrite the message:"
        text = chat_text(sys, usr, max_tokens=120, temperature=0.7)
        if text:
            return text.strip().strip('"')
    # Heuristic: light tone mirroring
    casual = any(w in (voice_sample or "").lower() for w in ("bro", "hey", "yo", "gonna", "wanna", "lol", "sup"))
    who = recipient or "there"
    if casual:
        return f"hey {who.split()[0] if who!='there' else 'there'} — quick one about {purpose.lower()}. got a sec to sort it?"
    return f"Hi {who.split()[0] if who!='there' else 'there'}, reaching out about {purpose.lower()}. Do you have a moment to align on it?"
