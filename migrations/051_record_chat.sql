-- The record chat (/chat): conversations a signed-in person holds with the
-- configured AI route about one record.  `user_id` is who is talking and owns
-- the conversation; `record_user_id` is whose record it reads -- the same
-- account, or the owner of a record shared with them.  Either account going
-- away takes the conversation with it: it quotes that record.
CREATE TABLE IF NOT EXISTS chat_conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_user
    ON chat_conversations(user_id, record_user_id, updated_at);

-- `tools_json` lists the record lookups an answer made, so the page can show
-- what it read.  `error` is the AIUnavailable reason key of a turn that failed
-- part-way; its partial text is kept rather than silently dropped.
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    tools_json TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, id);
