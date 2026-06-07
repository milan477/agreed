"""Shared session registry for invitations and multi-party coordination."""

from __future__ import annotations

import json
import time
import uuid

from .db import _adapt_sql, _conn, _lock, init_db


def init_sessions() -> None:
    init_db()


def _now() -> float:
    return time.time()


def create_session(host_user_id: str, data: dict) -> dict:
    init_sessions()
    sid = uuid.uuid4().hex[:16]
    code = uuid.uuid4().hex[:10]
    data = {**data, "session_id": sid, "invite_code": code, "host_user_id": host_user_id}
    now = _now()
    with _lock, _conn() as conn:
        conn.execute(
            _adapt_sql(
                "INSERT INTO platform_sessions(session_id, invite_code, host_user_id, data, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)"
            ),
            (sid, code, host_user_id, json.dumps(data), now, now),
        )
    return data


def get_session(session_id: str) -> dict | None:
    init_sessions()
    with _lock, _conn() as conn:
        row = conn.execute(
            _adapt_sql("SELECT data FROM platform_sessions WHERE session_id=%s"),
            (session_id,),
        ).fetchone()
    return json.loads(row["data"]) if row else None


def get_by_invite(invite_code: str) -> dict | None:
    init_sessions()
    with _lock, _conn() as conn:
        row = conn.execute(
            _adapt_sql("SELECT data FROM platform_sessions WHERE invite_code=%s"),
            (invite_code.strip(),),
        ).fetchone()
    return json.loads(row["data"]) if row else None


def update_session(session_id: str, data: dict) -> dict:
    init_sessions()
    now = _now()
    with _lock, _conn() as conn:
        conn.execute(
            _adapt_sql("UPDATE platform_sessions SET data=%s, updated_at=%s WHERE session_id=%s"),
            (json.dumps(data), now, session_id),
        )
    return data


def parse_invite_link(link: str) -> str | None:
    """Extract invite code from pasted URL or raw code."""
    link = link.strip()
    if not link:
        return None
    if "/join/" in link:
        return link.rsplit("/join/", 1)[-1].split("?")[0].split("#")[0]
    if link.startswith("agreed://"):
        return link.replace("agreed://", "").strip("/")
    if len(link) <= 12 and link.isalnum():
        return link
    return None
