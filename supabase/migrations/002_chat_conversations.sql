-- Chat threads (one row per conversation, messages stored as JSON text)

CREATE TABLE IF NOT EXISTS chat_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT 'New conversation',
    messages        TEXT NOT NULL DEFAULT '[]',
    created_at      DOUBLE PRECISION,
    updated_at      DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_chat_conv_user ON chat_conversations(user_id, updated_at DESC);

ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chat_conversations_isolation ON chat_conversations;
CREATE POLICY chat_conversations_isolation ON chat_conversations
    USING (user_id = current_setting('agreed.user_id', true));
