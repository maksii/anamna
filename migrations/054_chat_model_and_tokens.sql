-- The record chat's model picker and context indicator.
-- `model_key` is the `provider:model` the person chose for a conversation
-- ('' = the chat route's own model).  Each answer records what it cost:
-- `input_tokens` and `output_tokens` summed over its rounds, and
-- `context_tokens`, the input of its last round: how much the model read.
ALTER TABLE chat_conversations ADD COLUMN model_key TEXT NOT NULL DEFAULT '';
ALTER TABLE chat_messages ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN context_tokens INTEGER NOT NULL DEFAULT 0;
