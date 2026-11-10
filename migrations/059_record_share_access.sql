-- A share used to grant everything the viewer could do: read the record, ask
-- the AI assistant about it and order tests through the owner's lab account.
-- The owner now chooses a level per share.  Existing shares keep what they
-- could already do ('full'); a new share is created read-only unless its owner
-- chooses otherwise (see add_share).
ALTER TABLE record_shares ADD COLUMN access TEXT NOT NULL DEFAULT 'full' CHECK (access IN ('read', 'full'));
