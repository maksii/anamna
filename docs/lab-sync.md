# Lab sync

`src/anamna/labsync/` brings results in from labs' own customer APIs. The
operator enables each provider at `/admin/lab-connections` (all are off by
default); each person connects on `/profile` → Connections. A finished order's
PDF goes through the normal intake queue, and the lab's structured rows become a
cross-check of the parsed values (the "matches lab record" badges). Nothing is
ever marked verified automatically.

| Key | Lab | Credential | Module |
|---|---|---|---|
| `esculab` | Esculab | phone + SMS code in our form | `esculab.py` |
| `synevo` | Synevo | session cookie pasted from the browser | `synevo.py` |
| `expert` | Expert Hospital | phone + password (+ SMS code) in our form | `expert.py` |
| `paraskeva` | St. Paraskeva Medical Center | phone + SMS code in our form | `doctoreleks.py` |
| `veselka` | Veselka | phone + SMS code in our form | `doctoreleks.py` |

A provider is a module (or a `types.SimpleNamespace`) with `KEY`, `NAME`,
`VENDOR`, `DEFAULT_URL`, `SIGN_IN` and a `Client(url, secret, phone[, refresh])`
offering `check()`, `orders(person)`, `rows(order, person)` and
`pdfs(order, person)`. `SIGN_IN` is `"paste"` (default), `"password"` or
`"sms"`. App-style providers (`password`, `sms`) also give
`start_sign_in(url, phone, password, state)` and
`verify_code(url, challenge, code, state, phone)`. `VENDOR` must be exactly the
vendor name `ingest/classifier.py` gives that lab's PDFs: older uploads that
print no order number are matched by vendor, date and values.

## Whose record each lab person feeds

`check()` lists every person the lab account can see. Each one is linked
separately (`lab_person_links`, one row per account, provider and lab person)
to the holder's own record, to a family member's (anyone in a `record_shares`
relation, either direction), or to nobody.

- **Several lab people, one record.** A lab often lists one person more than
  once: Esculab keeps a profile per registration (a profile under a maiden name
  survives a surname change), and Synevo keeps both profiles after renaming one.
  Link each of them to the same record. Orders are keyed per record by their
  number (`lab_orders` primary key `owner_user_id, provider, order_id`), so an
  order listed under two profiles, or reached through two people's accounts,
  arrives once. The picker says when a record already receives another lab
  person ("also receives ..."), and shows the lab's own number for each person
  (`lab ID`), which is what tells two identically named profiles apart.
- **The guard is the profile, not the count.** A link is saved without asking
  only when the lab's date of birth and sex both equal the record's profile;
  anything else (a difference, or a value missing on either side) needs the
  holder's explicit confirmation, recorded as `mismatch_confirmed`. A record
  with no date of birth or sex in its profile therefore confirms every link.
- **Another person's results wait.** A link into somebody else's record
  fetches their orders as `awaiting`; nothing enters that record until they
  accept (each time, or from then on). See `migrations/036_lab_person_links.sql`.
- **The same person through two accounts.** A partner's family account may list
  you as well as your own account does, often under different lab ids. Both
  links can feed your record; whichever account reaches an order first keeps it
  (`account_user_id`), and the other sees it as already in the record.
- One lab login per person and provider (`lab_accounts` primary key
  `user_id, provider`): a second sign-in at the same lab replaces the first.
  Several profiles under one login, and the same person on a family member's
  login, are covered above.

## Orders with values but no PDF

Some finished orders have results in the lab's record but no file:
Expert Hospital's `has_file: false` (`labsync.unavailable_nofile`), a Synevo in-lab
order without a web id (`unavailable_offline`), or one behind an eHealth
one-time code (`unavailable_esoz`). When such an order carries rows with a
result, the sync files them as **the lab's own record of the order**:

- A `documents` row with `extraction_strategy='lab_api'` and
  `mime_type='application/json'`. Its source file, in `sources/uploads/YYYY-MM/`,
  is the JSON the lab's service returned (`<provider>-<order> lab record.json`).
  No PDF is generated. One page holds the rows as text, plus one report and an
  open review task, so the document meets the same rules as any other.
- Values go through `insert_observation`, so concepts resolve through the
  same alias path as a PDF row. They stay `extracted`. A lab "critical" flag
  becomes the vendor reading (`vendor_interpretation_source='lab_record'`),
  unless the row's own interval holds the value (a bound it includes counts):
  then the bounds judge it, as they would on paper. A row name that is only a
  number and a word («16 генотип») is stored with its test in front
  («ПЛР. ВПЛ ВКР, 16 генотип»).
- The order moves to `imported`, and `error_key` keeps the reason no PDF exists.
  The profile card shows it as **in your record, no PDF**. The document page
  shows "Reported by the lab's online service — no PDF issued" with the lab, the
  order number and the date. The metric history labels the value the same way.
- A lab record is never cross-checked against itself, never re-read and never
  listed as stale.
- Lifecycle:
  - A re-sync with the same rows does nothing.
  - If the lab amends the rows, a new record is filed and the old one is
    marked as its duplicate.
  - If a real report arrives, it takes the order over: the lab attaches the PDF
    (normal download), or the person uploads one with the order number (linked
    on the next sync). The record is then marked as that report's duplicate,
    and its values are removed by `mark_document_duplicate`. If the person
    verified a value the report does not hold, the record stays.
  - A value the report's reading lacks (a row the cross-check calls missing)
    stays in the record: after every cross-check the record holds exactly
    those rows and stands beside the report, and it is set aside again once
    the report reads them all. A record a person marked as a duplicate is left
    alone.

## After every cross-check

- The cross-check pairs the lab's rows with the order's own document first
  (or the document it was marked a copy of), then with other documents that
  print the order number. A document in a duplicate relation with the order's
  document, or the newer side of one, is a copy and never takes part.
- A lab flag on a value the printed band holds is not adopted, and an earlier
  adoption is taken back: the printed band decides, on an inclusive bound too.
- Esculab culture comments (`comments`, each organism's `defaultComment`) go
  into the note of the value they name, in the lab's words, matched by
  specimen. A comment that only restates a value is skipped.
- A document whose page prints no collection time takes the order's
  `ordered_at` (never later than the report day); a re-read keeps it.
  - Deleting the record makes the order `removed`, as for any document.

## Esculab sign-in

Mapped from the Esculab Android app 3.0.6 (`com.mak.elab`, React Native) on
2026-11-08 by static analysis of its Hermes bundle (`hermes-dec`; the
artefacts are in `work/esculab-apk/`, which is gitignored). The app's server
is `https://cabinet-api.mz-group.com.ua`; `esculab.com` fronts the same
backend (a stored token answers `findPatientSite` on both, and `/api/auth/*`
answers identically on both), so the configured address serves sign-in and
results alike and the default stays `https://esculab.com`.

1. `POST /api/auth/authorise` `{"phone": "+380XXXXXXXXX", "uuid": <uuid4>}`.
   The app builds the phone as `+380` and 9 digits and makes a fresh uuid per
   attempt; Esculab texts a 4-digit code. The app ignores the reply; we refuse
   only on an HTTP 4xx (`labsync.sms_error_phone`) or 429 (throttled).
2. `POST /api/auth/application/accept` `{"code", "uuid"}` with header
   `AccessPhone: <phone>`. The reply has one entry per role on the number,
   `{clientType: "PATIENT"|"DOCTOR", tokens: {token, exist, ...}}`; the
   app's ConfirmFlow keeps the PATIENT entry. No PATIENT entry is the app's
   "User not found", and `exist: false` sends the app to create a patient
   profile first; both are `labsync.esculab_error_no_patient` here. A wrong
   code is an HTTP 4xx with Spring's error JSON (`labsync.password_error_code`).
   The older patient-only `POST /api/auth/accept` (`{token, exist}`) is
   exported by the app but not called by its code screen; its reply shape is
   read too, defensively.

Stored: the PATIENT token as `secret` (a JWT; `exp`, read without verifying
the signature, is `secret_expires_at`, about a year out), the phone as
`+380XXXXXXXXX` (the same form pasted connections held, and what `AccessPhone`
needs), and an empty `refresh_secret`: Esculab issues no renewal token, so
when the token ends the person signs in again. Every signed-in call sends
`Authorization: Bearer <token>` and `AccessPhone: <phone>`, exactly as the
earlier pasted-token connections did, so those keep working unchanged.

## Doctor Eleks clinics

Doctor Eleks ([doctor.eleks.com](https://doctor.eleks.com)) is a clinic
information system made by ELEKS. Each clinic using it ships its own build of
one white-label Expo/React Native patient app (`com.eleks.<clinic>`). The
protocol below was mapped from the St. Paraskeva 1.8.2 and Veselka 1.6.5 builds
(Hermes bytecode, decompiled with `hermes-dec`). The two builds have the same
procedure names; they differ only in a tenant id.
This is not the platform Expert Hospital uses: Expert Hospital is a Flutter app talking to its
own REST backend.

- **One server for every clinic.** All calls go to `https://portal-doctor.eleks.com/api`.
  The clinic is identified by the `installationId` in each request body. Each
  APK has it in its `installationConfig` module.
- **Every call is a stored procedure.** The app POSTs
  `{"name", "installationId", "params": [{"name", "value"}]}`. It sends to
  `/api/va` when the procedure name contains `Anonymous`, and otherwise to
  `/api/v` with a bearer token. Signed-in calls also carry `Login`. If a call
  sends a parameter the procedure does not declare, the server rejects it.
- **Sign-in.** The app's phone mode, which the server enables for both clinics:
  1. `spiAnonymousAuthorizeByPhone {Phone}` makes the clinic text a code.
  2. `spiAnonymousAuthorizeByPhone {Phone, OTPCode, SessionGUID}` returns one
     account. If the phone is registered for several people, it returns a list
     of `{patientID, patientName}`; the person picks one and the call is repeated
     with `PatientID`.
  3. `POST /api/token` with `grant_type=password` and
     `username=<login>@@@<installationId>`. We store the access and refresh
     tokens, never the server-issued password.
  4. Renewal: `spiAnonymousTokenRefresh {RefreshToken}`, sent once `expires` has
     passed.
- **People on the account.** `spiUserPatientDetails` returns `patientList`.
  The account's own person is first (`isMain`).
- **Login.** Every signed-in call carries `Login`: the `login` of the
  `/api/token` reply (the clinic's patient number, the `Номер` printed on its
  reports), falling back to the sign-in row's `userLogin`. Sending `userLogin`
  when the token named another login reaches an account with no medical card:
  an empty profile and empty lists.
- **Documents, by following the server's menu.** Each clinic names its
  procedures differently, so nothing is hard-coded but the menu entry's name:
  1. `spzIBWApplicationDetails {DeviceIdentifier}` → `menu`; the entry named
     `Document` («Документи») carries the documents screen's action
     (St. Paraskeva `spzIBWDocumentList`, Veselka `spzIBWDocumentList_New`).
  2. That screen's `CTTab` cells are its sub-tabs, each a call of the same
     procedure with the tab's params (St. Paraskeva: `Mode=Document` with
     `DocumentRoleRef` «Веб доступ - Консультації/Лабораторія/Обстеження», and
     `Mode=Files`; Veselka: `Mode=Document|Diagnostics|Files`). The reply lowers
     the first letter of each param name; the call takes it as written in
     `actionXml` (`Mode`, `DocumentRoleRef`).
  3. A document is a `List` cell whose action is `spzIBWDocumentView
     {documentID, presentationName}`. Date: `orderValue` (ISO, St. Paraskeva) or
     the printed `text1` day (Veselka). Title: `text2`. Cells without that action
     (upload buttons, spacers) are skipped, and so are blank consent forms
     (titles with «згода»).
  4. `spzIBWDocumentView` → a `WebView` whose `iosUrl` (and the share action's
     `url`) is `/api/document?request=<base64 of documentId, validateId,
     presentationName, login>&installationID=…`: the clinic's PDF, fetched with
     a plain GET as the app does. Only a URL on the clinic server is followed.
- **Values come from the PDF.** The screens carry none, so `rows` is empty and
  there is no clinic-side cross-check; the PDF goes through intake like an
  upload, and a file already uploaded by hand (same bytes) is linked.
- **One person per account.** The list has no person parameter
  (`@PatientID is not a parameter`): it is the active medical card's. A family
  member (`isMain` false) stops the sync with
  `labsync.doctoreleks_error_unmapped` rather than receive the holder's files.

### Adding another Doctor Eleks clinic

1. Get the clinic's `installationId` from its APK. Decompile
   `assets/index.android.bundle` and search for `installationId': '`. Or ask
   the clinic.
2. Add one line to `CLINICS` in `labsync/doctoreleks.py`:
   `clinic("<key>", "<English name>", "<classifier vendor name>", "<installationId>")`.
3. Make sure `ingest/classifier.py` recognises the clinic's PDFs under that vendor
   name. Add a `PHRASES` entry for the Ukrainian display name.

The clinic needs no messages, template changes or migrations of its own: the
UI uses the shared `labsync.doctoreleks_*` and `labsync.sms_*` messages, with
the clinic's name filled in.

### Probing a clinic

The account holder signs in through `/profile`, never an agent, because the
clinic texts the code to their phone. Any probing of a live clinic account uses
the token stored by that sign-in, is read-only, never renews the token, and keeps
its captures out of the repository (they are patient data).

Known unknowns:

- How a family member's documents are reached (the documents screen's
  `spzIBWProfileSelectPopup` switches the active card).
- The `patientList` fields for date of birth and sex. We read `birthDate` and
  `sex` as the likeliest names; while those are missing, the person confirms
  the match by hand.
- How long the refresh token lasts, and whether signing in here signs the
  clinic's app out on the phone.
- Whether lab values arrive padded with zeros, as Expert Hospital's do. Trailing zeros
  are trimmed either way.
