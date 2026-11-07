# Telegram companion

Telegram is an optional, separately activated view of an account owner's own
record. Shared records and administrator privileges are never inherited by the
bot. The profile explains that bot conversations pass health data through
Telegram and are not end-to-end encrypted.

## Activate and connect

1. Create a bot with [@BotFather](https://t.me/BotFather). Set
   `ANAMNA_TELEGRAM_BOT_TOKEN` in the server environment. Keep the token
   out of version control, logs, screenshots and URLs you share.
   The default local web entry point also accepts it in the private `.env`,
   including the `telegram-bot-token` alias. The optional username uses
   `ANAMNA_TELEGRAM_BOT_USERNAME` or `telegram-bot-name`; activation checks
   the actual identity with Telegram. Explicit process settings take precedence.
2. Open **Administration → Telegram**. Choose **Polling** on a local computer
   or **Webhook** for an externally reachable HTTPS installation. A public
   Anamna URL supplies authenticated document links in either mode.
3. For webhook mode, also set `ANAMNA_TELEGRAM_WEBHOOK_SECRET` to a
   random 32–256 character value using letters, digits, `_` and `-`. Telegram
   delivers to `/api/telegram/webhook`; the server verifies its secret header
   before reading the request body.
4. Select **Activate bot and apply settings**. This contacts Telegram to
   validate the bot, install English/Ukrainian private-chat commands with an
   English fallback for other client languages, and configure the command menu
   and chosen transport. Polling explicitly removes
   an existing webhook without dropping pending updates. A conflicting external
   poller is reported and processing stops; stop that other instance and activate
   again. Use one database/deployment for each bot token.
5. In **Profile → Connections → Telegram**, read the privacy notice, select
   consent and connect. Open the generated Telegram link and press **Start**.
   The link expires after ten minutes, can be used once and is stored only as
   a SHA-256 hash. A replacement invalidates previous links.

One account owner links to one Telegram user/private chat. Reconnecting another
identity requires disconnecting the existing link from the authenticated profile.
Disconnecting cancels pending responses and completion notifications. Messages
already delivered remain in Telegram and may be removed there separately.
An HTTP delivery already in flight cannot be recalled by disconnecting.

## In the chat

`/menu` and `/start` open buttons for results, documents, search, upload,
recent uploads, the linked account, language and help. Every card has back/home
navigation, and lists paginate. `/cancel` clears conversational search/upload
state. `/language` switches between English and Ukrainian independently of the
website locale. `/help` lists every command with what it does.

- `/uploads` lists the ten newest files of the record (from the bot or the
  website) and where each stands: waiting, being read, added with its value
  count and whether it still needs review, already in the record, or not
  added and why.
- `/account` names the Anamna account (display name and email) this chat is
  connected to and since when.
- `/unlink` asks first, then disconnects the chat exactly as **Disconnect** in
  Profile does. The confirmation reply is queued without an owner, since
  disconnecting cancels everything queued for the owner.

The command menu is installed on activation, so an existing installation shows
the new commands after **Activate bot and apply settings** is applied again;
typed commands work either way.

Results show stored values, units, dates, source documents and whether a person
verified the extraction. Laboratory intervals are labelled as laboratory text;
the bot does not generate diagnoses or invent targets. Device history uses the
same source-selection functions as the website. Search covers metric names,
values, document titles, filenames and the owned document search index.

Opening a document first shows metadata. **Send original to this chat** is the
separate explicit action that sends its original bytes. Ownership and a current
account link are checked again immediately before delivery. Public document
links require normal Anamna authentication and never carry bearer tokens.

Attach PDF, JPEG, PNG, TIFF, ZIP or Telegram photos, up to 20 MB per attachment.
Files sent as attachments preserve scan quality. Office formats should be
exported to PDF first; the existing extraction pipeline does not support them.
The bot checks declared and downloaded size, file signatures and supported
extensions. Telegram download redirects and unsafe paths are refused. ZIP files
go through the existing bounded archive ingestion, including its traversal,
nested archive, entry count and expanded-size protections.

Uploads enter the same persistent `upload_jobs` pipeline as web uploads, retain
the same human verification requirements, and write an audit event. Each file
is one job with its own directory (every Telegram photo is called `photo.jpg`),
so each retains its own progress and provenance.

### Several files at once

Telegram delivers an album, a multi-forward or a gallery selection as one
update per file, possibly concurrently, out of order and, after a restart,
again. The bot handles them as one upload:

- **Exactly once.** The inbox is keyed by `update_id` in SQLite, so a retried
  or redelivered update (including across a process restart) adds no job and
  no reply. Two workers never claim the same update.
- **One batch.** A file joins the batch its chat is still collecting: one that
  has not been acknowledged yet (`telegram_uploads.notified_state` empty).
  Every job of the batch shares one `upload_jobs.batch_id`, which is also what
  the website's upload queue groups by.
- **One acknowledgement.** Files get no reply of their own. Once files stop
  arriving (`BATCH_QUIET`, 4 seconds since the last receipt, and no message of
  that chat still in the inbox) the chat gets one message, for example
  "Received 5 files. Reading them now; I will send one summary when all are
  done.", with a **Cancel this upload** button. A file after that starts a new
  batch.
- **One summary** when the last file is read: a heading with the count, a line
  of totals (added / already in your record / not added) and one line per file,
  at most 20 with the rest counted. Document buttons, the upload-queue link and
  **Undo this upload** follow. A batch that settled at once (only duplicates or
  refusals) gets the summary without an acknowledgement.

Per file, the summary says:

| Outcome | Line |
|---|---|
| New document | `scan.pdf: added as <title>, 12 values.` (or "no values could be read automatically") |
| Same bytes already in the record | `scan.pdf: already in your record as <title>. Nothing was added.` |
| Same report in a different file | the added line plus "It looks like a copy of `<title>`; confirm that on its page in Anamna." |
| Refused at the door | `letter.docx: not added. Use PDF, JPEG, PNG, TIFF or ZIP. ...` |
| Over Telegram's 20 MB download limit | `huge.pdf: not added. The file is empty or exceeds 20 MB. ...` |
| Failed while reading | `scan.pdf: not added.` with the intake queue's reason |

A ZIP is reported by the files that came out of it. Videos, voice messages and
other media are refused with the supported-format line and never downloaded.
Refused files are recorded as failed rows of the batch (no bytes kept), so the
website's upload queue shows them too.

**Duplicates.** Same bytes never become a second document: the door checks the
record by SHA-256, and the intake queue checks again before reading a file, so
the same scan twice in one album, or sent again while its first copy waited in
the queue, is filed once and reported as already there. A same-report copy in
different bytes is imported and linked by the record's suggested `duplicate` /
`reprint` relation, which a person confirms on the document page; the bot
reports it as a likely copy and changes nothing about that rule.

**Cancel and undo.** Both buttons ask first, then remove only what this upload
created: files still waiting are cancelled and their bytes removed, documents it
added are deleted with their source files. Files that were already in the
record stay. Undo is refused while one of its files is being read, after 24
hours, and when the record already builds on a document (a value a person
checked, a device import, an exact copy filed under it, a later upload pointing
at it); the refusal says to delete on the document page in Anamna instead.

## Reliability and privacy boundaries

- Inbox update IDs are unique. Handling a received update and publishing its
  replies/upload jobs occur in one SQLite transaction. Replayed updates cannot
  relink an account, enqueue an upload twice or duplicate response records.
- Downloads and outgoing API calls run outside database write transactions.
  Short persisted processing/sending claims recover after three minutes;
  downloaded files are published only after rechecking the current account link
  and activation state. A failed publication removes its newly written source.
- A renewable-duration SQLite lease serializes workers across processes. A
  process crash releases database transactions; the lease expires after three
  minutes. Poll offsets are advanced only after each update is durably stored.
- Telegram errors use localized fixed keys, never upstream error bodies or
  credential-bearing URLs. Rate-limit retries honor `retry_after`; transient
  failures back off. Invalid authentication or a transport conflict disables
  processing and appears on the administrator page.
- Delivery is **at least once**, not exactly once: Telegram's send APIs have
  no idempotency key. A process crash after Telegram accepted a send and before
  SQLite recorded its acknowledgement can repeat that message. Medical uploads
  and link-token consumption remain deduplicated.
- Processed inbox content and successfully delivered/terminally failed outbox
  payloads are erased; their IDs and fixed status/error keys remain for replay
  protection. Queued payloads are private local medical data and must be protected
  and backed up with the rest of the database.
- Delivery uses `protect_content` and disables link previews. These reduce
  accidental forwarding/preview exposure; they cannot prevent screenshots or
  substitute for the explicit Telegram privacy consent.
- Secret rotation lives in the server environment. Reapplying settings reloads
  the token. Changing to a different bot username revokes existing links and
  inbox/outbox state so a previous bot's identity mappings cannot carry over.

## Verification

Run the isolated synthetic API harness (no Telegram account or live token used):

```bash
uv run pytest tests/python/test_telegram.py -q --basetemp=work/pytest-telegram
```

The harness exercises activation, transport switching, private-only single-use
linking, expiry/replay, ownership and tampered callbacks, metadata-before-original,
revocation before delivery, multilingual menus/search/cancel, upload signatures
and size limits, shared intake publication, deduplication, final notifications,
retry/restart recovery and competing-worker leases. Batches are covered too:
a mixed album (PDF, an in-album duplicate, ZIP, a file already in the record,
Office, oversize), concurrent and out-of-order delivery with every update sent
twice, redelivery after a restart, a file resent while its first copy waited,
a same-report copy in different bytes, unsupported media, the quiet window,
long batches, summaries in English and Ukrainian with their plural forms,
undo and cancel with each refusal, `/uploads`, `/account`, `/help` and
`/unlink`. Live verification requires
the operator's bot token, activation and a consenting user who has linked their
own chat; use synthetic documents for that verification.

Protocol references (reviewed 2026-09-08):
[Bot API](https://core.telegram.org/bots/api),
[Bot features](https://core.telegram.org/bots/features),
[Bot interface guidelines](https://core.telegram.org/bots/guidelines).
