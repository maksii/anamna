# OpenWearables synchronization and outgoing webhooks

Anamna receives OpenWearables outgoing webhooks and independently reconciles
linked accounts with the pull API. A remote account must already be explicitly linked
to a local account. A webhook never creates a patient or chooses an account by email.

## Verified upstream contract

Reviewed against the official documentation, official `main` source, and a deployed
server's read-only OpenAPI document. The documentation index is
[llms.txt](https://openwearables.io/docs/llms.txt).

The [outgoing webhook router](https://github.com/the-momentum/open-wearables/blob/main/backend/app/api/routes/v1/outgoing_webhooks.py)
explicitly accepts **developer JWT or API key**. Anamna normally sends
`X-Open-Wearables-API-Key`. Older JWT-only examples in the
[webhook guide](https://openwearables.io/docs/api-reference/guides/webhooks)
do not mean every deployed release accepts the same authentication. A deployed
server has been seen to accept its API key for data pulls but return 401 for webhook
endpoint management, with JWT authentication in its OpenAPI document. A public
event-types endpoint that answers does **not** prove Svix is enabled. Live subscription
activation requires a valid developer JWT or a server release supporting API-key
management.

For older deployments, set `ANAMNA_OPENWEARABLES_WEBHOOK_TOKEN` to an explicit
developer Bearer token. The executable environment loader accepts the existing
`openwearables-token` alias. This token is only sent to webhook management paths;
data pulls retain API-key authentication. Changing the configured server binds the
old token to its previous address rather than sending it to the replacement host.
After changing servers, explicitly replace the token and its
`openwearables_webhook_token_server` setting before using it with the new server.

| Action | API path under `/api/v1` | Shape |
| --- | --- | --- |
| Create endpoint | `POST /webhooks/endpoints` | JSON `url`, `description`, `filter_types`, `user_id` |
| List endpoints | `GET /webhooks/endpoints` | Plain endpoint array |
| Update endpoint | `PATCH /webhooks/endpoints/{id}` | Same fields; `user_id: null` clears the user scope |
| Disable delivery | `DELETE /webhooks/endpoints/{id}` | Empty 204 response |
| Read signing key | `GET /webhooks/endpoints/{id}/secret` | `{"key":"whsec_..."}` |
| Send example | `POST /webhooks/endpoints/{id}/test` | JSON `event_type` |
| Delivery evidence | `GET /webhooks/endpoints/{id}/attempts` | `data`, `done`, `iterator`, `prevIterator` |

[Endpoint schema](https://github.com/the-momentum/open-wearables/blob/main/backend/app/schemas/webhooks/endpoints.py)
defines `user_id` as one UUID or null, and `filter_types` as an optional string list.
One all-user subscription can cover multiple locally linked people; a per-user
subscription adds another inbound scope check. Multiple explicit per-user subscriptions
can select a subset of remote users. The upstream list-endpoints handler currently
returns the first Svix page as a plain array; Anamna records a remotely created
endpoint ID immediately so normal edits and secret-retrieval retries do not need to
rediscover it from that list.

The current [event emitter](https://github.com/the-momentum/open-wearables/blob/main/backend/app/services/outgoing_webhooks/events.py)
uses an envelope `{"type":"resource.action","data":{"user_id":"...",...}}`.
Timeseries deliveries include **every sample**, not merely a notification. A sample
contains timestamp, metric type, numeric value, unit, source metadata, timezone offset,
and sometimes `is_daily_total`. Large batches are split into chunks of at most 2,500
samples with `chunk_index` and `total_chunks`. `sample_count` describes the whole
batch, not the individual chunk. Current source emits both group and granular series
events; their samples are deduplicated independently of message IDs.

## Receipt and signature guarantees

`POST /webhooks/openwearables/{receiver_id}` accepts at most 1 MiB, counting bytes
while reading the request stream even if Content-Length is absent or dishonest.
It verifies `svix-id`, `svix-timestamp`, and every whitespace-separated `v1,...`
signature against the **unaltered body bytes**. The signed content is
`message_id.timestamp.raw_body`; the key is base64-decoded after removing `whsec_`,
and the MAC is HMAC-SHA256. Both past and future timestamps beyond 300 seconds are
rejected. Comparisons use `hmac.compare_digest`.

Saving an endpoint refreshes its signing key. When that key changes, the previous
key remains valid for 24 hours, allowing in-flight signed attempts during rotation.
Signatures are never treated as local login credentials and no session/CSRF bypass
is granted to management actions.

A **202** is returned only after one SQLite transaction commits the immutable receipt,
its owner-specific targets, full included samples, and reconciliation jobs. A database
failure produces 5xx, allowing Svix to retry. `(subscription_id, message_id)` is unique.
An authenticated repeat with identical bytes is acknowledged without new jobs;
the same ID with different bytes produces 409. The timestamp remains checked on
replays because Svix signs delivery attempts using a fresh timestamp.

Unmatched remote users and events outside a subscription's scope get delivery
metadata only: their medical body is not saved. Unknown events for linked users
are retained in full and visibly marked `unsupported`, rather than acknowledged as
successfully mapped. Chunk payloads are kept in full; a missing chunk is recovered
by the scheduled full-window pull, and each received chunk can be inspected in its
receipt. Unknown metric types remain in the raw sample store even without a chart.

Deleting a local account cascades its samples, jobs and target rows. A SQLite trigger
erases receipt medical bytes when its last owning account disappears. Replacing a
link clears the previous person's imported data, archived samples and receipt targets;
unlinking simply stops future synchronization and keeps the person's existing record.

## Raw archive

Original samples live in `openwearables_raw_days`: one zlib-compressed JSON blob per
local account, remote account, UTC day and series type, holding the exact former rows
`[sample_key, timestamp, received_at, payload_json]` (migration 040, module
`openwearables_archive`). `openwearables_archive.iter_samples` is the only reader.
Status pages read `openwearables_raw_totals`, kept exact by triggers; nothing on a
render path counts samples.

The pre-040 per-sample table (`openwearables_raw_samples`, which can reach millions of
rows and several gigabytes) is no longer written. A background thread started beside the worker
copies it out in batches of about half a second of work per write transaction; each
day is read back tuple for tuple and claimed in `openwearables_raw_conversion` with
its old rows' count, exact value sum and digest. Write paths claim the days they touch,
so a claimed day's old rows are never read again. The ledger is the progress, so a
restart resumes. Old rows are not deleted one by one: their hashed primary key would
dirty a random index page per row. `python -m anamna.openwearables_archive
reclaim` refuses until every old day is copied and every fingerprint matches, then
drops the table and runs `VACUUM`; `status`, `verify`, `fingerprint` and `compare`
observe and prove the conversion by content.

## Durable worker and history

The application lifespan starts the worker; visiting a page is unnecessary. Every
linked account gets catch-up twice daily (today and the three days before it) and a
monthly historical reconciliation that is incremental: it restarts seven days before
the previous complete history check of the same link ended. Only a new link, or an
administrator ticking "Include full history", fetches from `EPOCH_DAY`.
Recent and historical jobs remain separate. Each successful seven-day chunk moves
to the back of the ready queue, allowing recent work and other accounts to proceed.
The monthly scheduler preserves unfinished history's next date, including jobs
awaiting explicit retry; it never restarts that work at the first date.
Backfill begins at the existing configurable-code `EPOCH_DAY` (2015-01-01).
The admin can queue one, selected or all local linked accounts and request full
history or retries.

SQLite jobs bind the local owner, remote server URL, remote user ID and random link
generation. Relinking (even to the same UUID), unlinking and changing the server
invalidate old work. Every measurement write rechecks the binding inside its write
transaction. A server change disables old receiver secrets and preserves already
imported provenance until an account is explicitly replaced.

The worker claims a 180-second lease and renews it every 30 seconds. Expired leases
are reclaimable after process restarts. It serializes each owner's jobs across
processes. Webhook arrivals coalesce for 15 seconds; arrivals during a running job
create a follow-up job so they cannot be lost when that job completes. Work runs in
seven-day windows with a two-second pause between successful windows and exponential
retry delays up to an hour. After eight consecutive failures a job needs attention;
its receipt and next date remain available for explicit retry. Failed datatypes do
not discard successful datatype imports, and a failed window is never marked complete.

Raw history can contain more than the 50,000 samples allowed by one bounded
500-page cursor read. Only that explicit page-budget condition triggers adaptive
time subdivision; empty windows retain their single request, and HTTP errors,
malformed responses or stalled cursors still fail without replacing the window.
Subintervals overlap at their exact UTC microsecond boundary. A private temporary
SQLite spool deduplicates the stable sample identity before aggregation, with the
later fetched correction winning, and retains all original payload fields. This
keeps memory bounded by an interval and aggregate groups rather than total history.
An over-budget indivisible timestamp fails explicitly instead of skipping samples.
After every subinterval succeeds, a single account/lease-checked transaction
replaces the window's days in the raw archive and the successfully mapped daily rows.
Spools are closed and removed on normal completion, errors and cancellation. The profile translates
failed dataset names; technical error codes remain in the administrator view.

First activation creates both recent and historical work when no durable schedule
exists, even if an older importer recorded a previous backfill. The recent range is
today minus three days through today, inclusive (one chunk). History from
`EPOCH_DAY` is several hundred seven-day chunks per account. Each chunk makes at least
nine data requests, with additional requests for pagination; for two accounts the
pacing alone takes about 40 minutes. Network time,
raw sample volume, SQLite writes and retries add to that lower bound. There is no
remote provider synchronization command: the worker reads already-held server data.

Before activation, retain a SQLite backup and content hashes for clinical tables
and non-OpenWearables imports. During a supervised first run, inspect each account's
job next date, status, attempts and dataset error codes; confirm both recent jobs
finish while historical next dates advance. Use read-only SQLite snapshots for
consistent comparisons while the worker writes. Do not use row count alone as a
loss detector: legacy generic bridge rows are replaced with provider-specific rows,
and an upstream deletion can legitimately reduce counts. Compare mapped content
against archived responses for the completed date windows, check unchanged content
outside those windows and in other imports, and rerun an audited window to confirm
stable content and sample counts. Check SQLite integrity and foreign keys as well.
If these checks disagree or a job needs attention, stop the worker and inspect the
retained response and failure code before retrying. Webhook management authentication
is independent of this polling worker; a management HTTP 401 does not disable pulls.

Pull endpoint contracts come from the
[official timeseries reference](https://openwearables.io/docs/api-reference/external:-timeseries/get-timeseries),
[events router](https://github.com/the-momentum/open-wearables/blob/main/backend/app/api/routes/v1/events.py),
[summaries router](https://github.com/the-momentum/open-wearables/blob/main/backend/app/api/routes/v1/summaries.py),
and [health-score router](https://github.com/the-momentum/open-wearables/blob/main/backend/app/api/routes/v1/health_scores.py).
Summaries/events/timeseries use cursors, health scores use offset, and users use
page numbers. Limits are respectively 400 for activity, 100 for other cursor
endpoints, and 1,000 for scores. Final dates include the complete day through
the following midnight for summaries, scores and sessions, trimming any returned
next-day boundary row. This matters: the deployed daily summary range truncated a
`23:59:59` end and omitted the final day; scores also failed with a date-only start
and timezone-aware end. Timeseries use two timezone-aware edges through
`23:59:59.999999Z`, preserving fractional samples.
Known premature full-page endings are handled by overlapping the boundary and
deduplicating, never by skipping one second or one day. An ambiguous full boundary
fails before replacing stored rows. Cursor loops and page exhaustion also fail
explicitly, preserving the previous complete window.

Every raw timeseries type is fetched, including types without a display mapping.
Known extra catalog metrics such as blood pressure, walking heart rate, exercise
time, cycling/swimming distance, mobility and environmental measurements are mapped
from these samples. Daily totals replace intraday fragments from the same source
and date; multiple daily totals use the latest value. Original full payloads remain
available even when unit conversion or a display mapping fails.

The API's [series definitions](https://github.com/the-momentum/open-wearables/blob/main/backend/app/schemas/enums/series_types.py)
serialize unit identifiers such as `percent`, `kg_m2`, `meters`, `m_per_s`, `brpm`,
and `ml_kg_min`; these are normalized at the OpenWearables boundary before physical
conversion.

Upstream currently documents that recovery summaries contain WHOOP only. Resting
heart rate is therefore also read from its actual raw timeseries, retaining source
identity. Complete response JSON is kept for daily summaries, scores and sessions,
including fields without a dedicated chart. Window reconciliation handles removed
or updated data without deleting rows belonging to other imports. Connection-revoked
notifications are operational evidence and do not themselves erase clinical history.

## Operations and activation

Apply the migrations, configure the server API key, and use the OpenWearables admin
page to enter Anamna's externally reachable HTTPS base address. Saving a
subscription creates/updates the remote endpoint and retrieves its signing key.
No endpoint is created by a GET request or by worker startup. The OpenWearables server
must have outgoing webhooks and Svix enabled; its API returns 503 otherwise.

Review subscription status, recent receipts, queued checks, current date windows,
retry counts and preserved sample counts on the admin page. Delivery-attempt evidence
is retrieved only through an explicit admin request and strips embedded medical
payloads from the remote diagnostic response. Profile status is filtered to its
owner. API keys and webhook signing secrets never appear in these contexts.

The upstream test API uses synthetic fixed sample user IDs and may send an untagged
message, so a per-user endpoint may not receive its example and an all-user endpoint
will normally record `unlinked`. That proves transport reachability only; it must
not import another person's test measurements into a linked record.

## HRV method correction

Oura's `average_hrv` is **RMSSD**, while HealthKit's `HeartRateVariabilitySDNN`
is **SDNN**. Oura API and direct export adapters now use
`heart_rate_variability_rmssd`. OpenWearables' explicit `avg_hrv_sdnn_ms` and
`avg_hrv_rmssd_ms` fields stay separate. No conversion, reference threshold, or
vendor-based guess changes one method into the other.

Migration 030 corrects only Oura-vendor rows imported by `oura` or `oura_api`.
It preserves numeric values and IDs, retaining both rows under distinct provenance
if a corrected destination already exists. HealthKit records—including an Oura
writer app—are excluded from this migration. The RMSSD concept already has separate
localized naming and metric guidance; this change does not copy SDNN reference bands.

Evidence: Oura's
[Cardiovascular Health white paper (February 2026)](https://ouraring.com/blog/wp-content/uploads/2026/02/Cardiovascular-Health-white-paper-February-2026.pdf)
identifies its HRV as rMSSD. Its
[HRV measurement explanation](https://support.ouraring.com/hc/en-us/articles/360025441974-Heart-Rate-Variability)
describes nightly averages of five-minute samples.

## Verification

Run `uv run pytest tests/python/test_openwearables.py tests/python/test_openwearables_webhooks.py tests/python/test_oura.py tests/python/test_device_importers.py --basetemp=work/pytest-ow-webhooks-unique`.
Use a unique basetemp for concurrent runs. Tests use throwaway local SQLite databases;
they neither create a remote endpoint nor synchronize a real provider account.
