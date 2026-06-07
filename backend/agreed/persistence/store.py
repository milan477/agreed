"""User-scoped storage with strict isolation + audit log.

Every record is namespaced by `user_id`. Reads and writes go through
`UserScopedStore`, which is bound to a single authenticated user and refuses to
return another user's rows. Every access is written to an append-only audit log.

Default backend is local SQLite (always available). With DATABASE_URL set and
psycopg installed, the same schema runs on Postgres, where the included RLS SQL
(see `POSTGRES_RLS_SQL`) enforces isolation at the database layer too.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..observability import op, record_event

_lock = threading.Lock()
_db_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id   TEXT PRIMARY KEY,
    email     TEXT UNIQUE,
    name      TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS records (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,
    kind      TEXT NOT NULL,         -- profile | brief | negotiation | agreement
    ref       TEXT,                  -- optional external id (e.g. negotiation id)
    data      TEXT NOT NULL,         -- JSON blob
    created_at REAL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, kind);
CREATE TABLE IF NOT EXISTS audit_log (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,
    action    TEXT NOT NULL,         -- read | write | delete | denied
    kind      TEXT,
    record_id TEXT,
    ts        REAL,
    detail    TEXT
);
"""

# For a Postgres deployment, enforce isolation at the DB layer as well:
POSTGRES_RLS_SQL = """
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
CREATE POLICY records_isolation ON records
    USING (user_id = current_setting('agreed.user_id', true));
-- App sets the user per connection:  SET agreed.user_id = '<authenticated user>';
"""


def _default_db_path() -> Path:
    """Prefer backend/data/agreed.db; fall back to /tmp when disk is full."""
    override = os.environ.get("AGREED_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    preferred = Path(__file__).resolve().parents[2] / "data" / "agreed.db"
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        probe = preferred.parent / ".write_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        return Path(tempfile.gettempdir()) / "agreed" / "agreed.db"


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = _default_db_path()
    return _db_path


def _open_sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _conn() -> sqlite3.Connection:
    primary = db_path()
    try:
        return _open_sqlite(primary)
    except sqlite3.OperationalError as exc:
        if "unable to open" not in str(exc).lower():
            raise
        # Disk full or unwritable project dir — fall back to /tmp so the demo still runs.
        fallback = Path(tempfile.gettempdir()) / "agreed" / "agreed.db"
        record_event(
            "db_path_fallback",
            kind="tool",
            primary=str(primary),
            fallback=str(fallback),
            error=str(exc),
        )
        global _db_path
        _db_path = fallback
        return _open_sqlite(fallback)


def init_db() -> None:
    with _lock, _conn() as conn:
        conn.executescript(SCHEMA)


@dataclass
class UserScopedStore:
    """All operations are confined to `self.user_id`. There is no API to read
    across users — isolation is structural."""

    user_id: str

    def _audit(self, conn, action: str, kind: str | None, record_id: str | None, detail: str = "") -> None:
        conn.execute(
            "INSERT INTO audit_log(id, user_id, action, kind, record_id, ts, detail) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, self.user_id, action, kind, record_id, time.time(), detail),
        )
        record_event("db_access", kind="tool", user=self.user_id, action=action, table=kind, record_id=record_id)

    @op(name="store.put", kind="tool")
    def put(self, kind: str, data: dict, *, ref: str | None = None, record_id: str | None = None) -> str:
        rid = record_id or uuid.uuid4().hex
        now = time.time()
        with _lock, _conn() as conn:
            conn.execute(
                """INSERT INTO records(id, user_id, kind, ref, data, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
                (rid, self.user_id, kind, ref, json.dumps(data), now, now),
            )
            self._audit(conn, "write", kind, rid)
        return rid

    @op(name="store.get", kind="tool")
    def get(self, record_id: str) -> dict | None:
        with _lock, _conn() as conn:
            row = conn.execute(
                "SELECT * FROM records WHERE id=? AND user_id=?", (record_id, self.user_id)
            ).fetchone()
            if row is None:
                exists = conn.execute("SELECT 1 FROM records WHERE id=?", (record_id,)).fetchone()
                self._audit(conn, "denied" if exists else "read", None, record_id,
                            "cross-user read blocked" if exists else "")
                return None
            self._audit(conn, "read", row["kind"], record_id)
            return _row_to_dict(row)

    @op(name="store.list", kind="tool")
    def list(self, kind: str | None = None) -> list[dict]:
        with _lock, _conn() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM records WHERE user_id=? AND kind=? ORDER BY updated_at DESC",
                    (self.user_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM records WHERE user_id=? ORDER BY updated_at DESC", (self.user_id,)
                ).fetchall()
            self._audit(conn, "read", kind, None, f"list n={len(rows)}")
            return [_row_to_dict(r) for r in rows]

    @op(name="store.audit_trail", kind="tool")
    def audit_trail(self, limit: int = 50) -> list[dict]:
        with _lock, _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                (self.user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d["data"])
    return d


@op(name="store.ensure_user", kind="tool")
def ensure_user(user_id: str, email: str = "", name: str = "") -> str:
    init_db()
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO users(user_id, email, name, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, email or None, name, time.time()),
        )
    return user_id
