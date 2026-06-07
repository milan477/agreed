"""Database connection layer — SQLite locally, Postgres (Supabase) in production."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import get_settings
from ..observability import record_event

_lock = threading.Lock()
_db_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id   TEXT PRIMARY KEY,
    email     TEXT UNIQUE,
    name      TEXT,
    created_at DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS records (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,
    kind      TEXT NOT NULL,
    ref       TEXT,
    data      TEXT NOT NULL,
    created_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, kind);
CREATE TABLE IF NOT EXISTS audit_log (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL,
    action    TEXT NOT NULL,
    kind      TEXT,
    record_id TEXT,
    ts        DOUBLE PRECISION,
    detail    TEXT
);
CREATE TABLE IF NOT EXISTS platform_sessions (
    session_id   TEXT PRIMARY KEY,
    invite_code  TEXT UNIQUE NOT NULL,
    host_user_id TEXT NOT NULL,
    data         TEXT NOT NULL,
    created_at   DOUBLE PRECISION,
    updated_at   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_sessions_invite ON platform_sessions(invite_code);
CREATE TABLE IF NOT EXISTS channel_index (
    channel    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    updated_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_channel_user ON channel_index(user_id);
CREATE TABLE IF NOT EXISTS chat_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    messages        TEXT NOT NULL,
    created_at      DOUBLE PRECISION,
    updated_at      DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_chat_conv_user ON chat_conversations(user_id, updated_at);
"""

POSTGRES_RLS_SQL = """
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS records_isolation ON records;
CREATE POLICY records_isolation ON records
    USING (user_id = current_setting('agreed.user_id', true));
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_log_isolation ON audit_log;
CREATE POLICY audit_log_isolation ON audit_log
    USING (user_id = current_setting('agreed.user_id', true));
ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_conversations_isolation ON chat_conversations;
CREATE POLICY chat_conversations_isolation ON chat_conversations
    USING (user_id = current_setting('agreed.user_id', true));
"""


def using_postgres() -> bool:
    return bool(get_settings().database_url)


def _adapt_sql(sql: str) -> str:
    return sql if using_postgres() else sql.replace("%s", "?")


def _default_db_path() -> Path:
    import os

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


def _open_postgres() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(get_settings().database_url, row_factory=dict_row)


@contextmanager
def _conn(user_id: str | None = None) -> Iterator[Any]:
    if using_postgres():
        conn = _open_postgres()
        try:
            if user_id:
                conn.execute("SELECT set_config('agreed.user_id', %s, true)", (user_id,))
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    primary = db_path()
    try:
        conn = _open_sqlite(primary)
    except sqlite3.OperationalError as exc:
        if "unable to open" not in str(exc).lower():
            raise
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
        conn = _open_sqlite(fallback)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _lock, _conn() as conn:
        if using_postgres():
            for statement in SCHEMA.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
            for statement in POSTGRES_RLS_SQL.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
        else:
            conn.executescript(SCHEMA)
