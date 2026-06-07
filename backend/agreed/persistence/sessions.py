"""Shared session registry for invitations and multi-party coordination."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .store import _conn, init_db

_lock = threading.Lock()

SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS platform_sessions (
    session_id   TEXT PRIMARY KEY,
    invite_code  TEXT UNIQUE NOT NULL,
    host_user_id TEXT NOT NULL,
    data         TEXT NOT NULL,
    created_at   REAL,
    updated_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_invite ON platform_sessions(invite_code);
"""


def init_sessions() -> None:
    init_db()
    with _lock, _conn() as conn:
        conn.executescript(SESSIONS_DDL)


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
            "INSERT INTO platform_sessions(session_id, invite_code, host_user_id, data, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, code, host_user_id, json.dumps(data), now, now),
        )
    return data


def get_session(session_id: str) -> dict | None:
    init_sessions()
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT data FROM platform_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def get_by_invite(invite_code: str) -> dict | None:
    init_sessions()
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT data FROM platform_sessions WHERE invite_code=?", (invite_code.strip(),)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def update_session(session_id: str, data: dict) -> dict:
    init_sessions()
    now = _now()
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE platform_sessions SET data=?, updated_at=? WHERE session_id=?",
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
