"""User-scoped storage with strict isolation + audit log.

Every record is namespaced by `user_id`. Reads and writes go through
`UserScopedStore`, which is bound to a single authenticated user and refuses to
return another user's rows. Every access is written to an append-only audit log.

Default backend is local SQLite (always available). With DATABASE_URL set and
psycopg installed, the same schema runs on Postgres/Supabase, where RLS enforces
isolation at the database layer too.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..observability import op, record_event
from .db import POSTGRES_RLS_SQL, _adapt_sql, _conn, _lock, init_db, using_postgres

__all__ = ["POSTGRES_RLS_SQL", "UserScopedStore", "ensure_user", "init_db", "using_postgres"]


@dataclass
class UserScopedStore:
    """All operations are confined to `self.user_id`. There is no API to read
    across users — isolation is structural."""

    user_id: str

    def _audit(self, conn, action: str, kind: str | None, record_id: str | None, detail: str = "") -> None:
        conn.execute(
            _adapt_sql(
                "INSERT INTO audit_log(id, user_id, action, kind, record_id, ts, detail) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)"
            ),
            (uuid.uuid4().hex, self.user_id, action, kind, record_id, time.time(), detail),
        )
        record_event("db_access", kind="tool", user=self.user_id, action=action, table=kind, record_id=record_id)

    @op(name="store.put", kind="tool")
    def put(self, kind: str, data: dict, *, ref: str | None = None, record_id: str | None = None) -> str:
        rid = record_id or uuid.uuid4().hex
        now = time.time()
        with _lock, _conn(user_id=self.user_id) as conn:
            conn.execute(
                _adapt_sql(
                    """INSERT INTO records(id, user_id, kind, ref, data, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET
                         data=excluded.data, updated_at=excluded.updated_at"""
                ),
                (rid, self.user_id, kind, ref, json.dumps(data), now, now),
            )
            self._audit(conn, "write", kind, rid)
        return rid

    @op(name="store.get", kind="tool")
    def get(self, record_id: str) -> dict | None:
        with _lock, _conn(user_id=self.user_id) as conn:
            row = conn.execute(
                _adapt_sql("SELECT * FROM records WHERE id=%s AND user_id=%s"),
                (record_id, self.user_id),
            ).fetchone()
            if row is None:
                exists = conn.execute(
                    _adapt_sql("SELECT 1 FROM records WHERE id=%s"),
                    (record_id,),
                ).fetchone()
                self._audit(
                    conn,
                    "denied" if exists else "read",
                    None,
                    record_id,
                    "cross-user read blocked" if exists else "",
                )
                return None
            self._audit(conn, "read", row["kind"], record_id)
            return _row_to_dict(row)

    @op(name="store.list", kind="tool")
    def list(self, kind: str | None = None) -> list[dict]:
        with _lock, _conn(user_id=self.user_id) as conn:
            if kind:
                rows = conn.execute(
                    _adapt_sql(
                        "SELECT * FROM records WHERE user_id=%s AND kind=%s ORDER BY updated_at DESC"
                    ),
                    (self.user_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    _adapt_sql("SELECT * FROM records WHERE user_id=%s ORDER BY updated_at DESC"),
                    (self.user_id,),
                ).fetchall()
            self._audit(conn, "read", kind, None, f"list n={len(rows)}")
            return [_row_to_dict(r) for r in rows]

    @op(name="store.audit_trail", kind="tool")
    def audit_trail(self, limit: int = 50) -> list[dict]:
        with _lock, _conn(user_id=self.user_id) as conn:
            rows = conn.execute(
                _adapt_sql("SELECT * FROM audit_log WHERE user_id=%s ORDER BY ts DESC LIMIT %s"),
                (self.user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    d["data"] = json.loads(d["data"])
    return d


@op(name="store.ensure_user", kind="tool")
def ensure_user(user_id: str, email: str = "", name: str = "") -> str:
    init_db()
    with _lock, _conn() as conn:
        conn.execute(
            _adapt_sql(
                "INSERT INTO users(user_id, email, name, created_at) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT(user_id) DO NOTHING"
            ),
            (user_id, email or None, name, time.time()),
        )
    return user_id
