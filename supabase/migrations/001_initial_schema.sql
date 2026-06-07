-- agreed schema for Supabase (Postgres)
-- Run in Supabase SQL Editor or via `supabase db push`

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

-- Row-level security for user-scoped tables
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS records_isolation ON records;
CREATE POLICY records_isolation ON records
    USING (user_id = current_setting('agreed.user_id', true));

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_log_isolation ON audit_log;
CREATE POLICY audit_log_isolation ON audit_log
    USING (user_id = current_setting('agreed.user_id', true));

-- Service role bypasses RLS; the backend sets agreed.user_id per connection.
