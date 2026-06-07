"""Chat conversations stored in Supabase/Postgres (one row per thread)."""

from __future__ import annotations

import json
import time
import uuid

from fastapi import HTTPException

from .db import _adapt_sql, _conn, _lock, init_db


def _now() -> float:
    return time.time()


def title_from_first_message(message: str, fallback: str = "New conversation") -> str:
    text = (message or "").strip()
    if not text:
        return fallback
    return text[:60] + ("…" if len(text) > 60 else "")


def _preview(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and (m.get("content") or "").strip():
            c = m["content"].strip()
            return c[:80] + ("…" if len(c) > 80 else "")
    return ""


def list_conversations(user_id: str) -> list[dict]:
    init_db()
    with _lock, _conn(user_id=user_id) as conn:
        rows = conn.execute(
            _adapt_sql(
                "SELECT conversation_id, title, messages, created_at, updated_at "
                "FROM chat_conversations WHERE user_id=%s ORDER BY updated_at DESC"
            ),
            (user_id,),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        messages = json.loads(row["messages"] or "[]")
        out.append(
            {
                "conversation_id": row["conversation_id"],
                "title": row["title"],
                "preview": _preview(messages),
                "message_count": len(messages),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return out


def get_conversation(user_id: str, conversation_id: str) -> dict | None:
    init_db()
    with _lock, _conn(user_id=user_id) as conn:
        row = conn.execute(
            _adapt_sql(
                "SELECT conversation_id, title, messages, created_at, updated_at "
                "FROM chat_conversations WHERE conversation_id=%s AND user_id=%s"
            ),
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        return None
    messages = json.loads(row["messages"] or "[]")
    return {
        "conversation_id": row["conversation_id"],
        "title": row["title"],
        "messages": messages,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_conversation(user_id: str, title: str = "New conversation") -> dict:
    init_db()
    cid = uuid.uuid4().hex[:16]
    now = _now()
    with _lock, _conn(user_id=user_id) as conn:
        conn.execute(
            _adapt_sql(
                "INSERT INTO chat_conversations(conversation_id, user_id, title, messages, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)"
            ),
            (cid, user_id, title[:120], "[]", now, now),
        )
    return {
        "conversation_id": cid,
        "title": title[:120],
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }


def save_messages(
    user_id: str,
    conversation_id: str,
    messages: list[dict],
    *,
    title: str | None = None,
) -> dict:
    init_db()
    now = _now()
    with _lock, _conn(user_id=user_id) as conn:
        if title:
            conn.execute(
                _adapt_sql(
                    "UPDATE chat_conversations SET messages=%s, title=%s, updated_at=%s "
                    "WHERE conversation_id=%s AND user_id=%s"
                ),
                (json.dumps(messages), title[:120], now, conversation_id, user_id),
            )
        else:
            conn.execute(
                _adapt_sql(
                    "UPDATE chat_conversations SET messages=%s, updated_at=%s "
                    "WHERE conversation_id=%s AND user_id=%s"
                ),
                (json.dumps(messages), now, conversation_id, user_id),
            )
    conv = get_conversation(user_id, conversation_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


def migrate_legacy_chat_history(user_id: str, legacy_messages: list[dict]) -> dict | None:
    """One-time import from old single chat_history blob."""
    if not legacy_messages:
        return None
    title = title_from_first_message(
        next((m["content"] for m in legacy_messages if m.get("role") == "user"), ""),
    )
    conv = create_conversation(user_id, title=title)
    return save_messages(user_id, conv["conversation_id"], legacy_messages)


def resolve_active_conversation(
    user_id: str,
    profile: dict,
    *,
    conversation_id: str | None = None,
    legacy_messages: list[dict] | None = None,
) -> dict:
    """Return the active conversation, creating or migrating as needed."""
    convs = list_conversations(user_id)
    if not convs and legacy_messages:
        migrated = migrate_legacy_chat_history(user_id, legacy_messages)
        if migrated:
            convs = list_conversations(user_id)
            profile["active_conversation_id"] = migrated["conversation_id"]
            return migrated

    target = conversation_id or profile.get("active_conversation_id")
    if target:
        conv = get_conversation(user_id, target)
        if conv:
            profile["active_conversation_id"] = target
            return conv

    if convs:
        conv = get_conversation(user_id, convs[0]["conversation_id"])
        if conv:
            profile["active_conversation_id"] = conv["conversation_id"]
            return conv

    conv = create_conversation(user_id)
    profile["active_conversation_id"] = conv["conversation_id"]
    return conv
