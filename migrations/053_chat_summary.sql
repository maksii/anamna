-- Compaction for long record chats (chat.py: pending_compaction / summarise).
-- `summary` is what the assistant is told about the earlier part of the
-- conversation; `summary_through` is the id of the last chat_messages row it
-- covers.  Messages after it are replayed verbatim; the page draws a marker
-- after that row.  0 means nothing has been summarised.
ALTER TABLE chat_conversations ADD COLUMN summary TEXT NOT NULL DEFAULT '';
ALTER TABLE chat_conversations ADD COLUMN summary_through INTEGER NOT NULL DEFAULT 0;
