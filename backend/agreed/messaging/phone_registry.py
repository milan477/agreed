"""Map phone numbers to user IDs for inbound SMS/voice webhooks."""

from __future__ import annotations

import time

from ..persistence.db import _adapt_sql, _conn, _lock, init_db
from .twilio_client import normalize_phone


def bind_phone(user_id: str, phone: str) -> str:
    """Register a user's phone for inbound routing."""
    channel = normalize_phone(phone)
    if not channel:
        return ""
    init_db()
    now = time.time()
    with _lock, _conn() as conn:
        conn.execute(
            _adapt_sql(
                "INSERT INTO channel_index(channel, user_id, updated_at) VALUES (%s,%s,%s) "
                "ON CONFLICT(channel) DO UPDATE SET user_id=excluded.user_id, updated_at=excluded.updated_at"
            ),
            (channel, user_id, now),
        )
    return channel


def lookup_user(phone: str) -> str | None:
    channel = normalize_phone(phone)
    if not channel:
        return None
    init_db()
    with _lock, _conn() as conn:
        row = conn.execute(
            _adapt_sql("SELECT user_id FROM channel_index WHERE channel=%s"),
            (channel,),
        ).fetchone()
    return row["user_id"] if row else None
