# Contract: the API after the backend restructure (wave 1)

Owner: BE-core. The full, typed contract is the OpenAPI schema:

```sh
cd backend && uv run virtubooth export-openapi -o ../frontend/openapi.json
cd frontend && pnpm gen:api        # openapi-typescript → src/api/schema.gen.ts
```

The export is deterministic (sorted keys, 2-space indent): commit it, CI diffs
it. It is built from dummy settings and every built-in extension, so your shell's
`VB_*` variables don't change it. Runtime docs (`/docs`, `/openapi.json`) stay off.

Everything in `analysis/architecture.md` §2 still holds (paths, auth levels,
cookies, CSRF, rate limits, check order of the upload pipeline, audit
vocabulary) except for the changes listed here. Paths are unchanged; no `/api/v1`.

## 1. New endpoints

| Route | Auth | Answer |
|---|---|---|
| `GET /api/me/photos` | guest (access + joined + not banned) | `MyPhotosOut {photos: GuestPhoto[]}`: the caller's own photos that are not hidden and not deleted, newest first, at most 60. Paused guests see theirs. Banned: 403 `banned` "Dieses Gerät ist gesperrt." |
| `GET /api/x/booth/filters` | access | `BoothFilters {filters: [{id, name, icon}]}`: the Fotobox catalogue in strip order (first = default). Replaces fetching `./filters.json`; the source stays `backend/src/virtubooth/extensions/booth/filters.json`. |

`GuestPhoto = {id, extension, seq, created_at, width, height, url, thumb_url}`
(the same object the upload returns as `photo`).

## 2. Changed or added fields (nothing was removed)

| Where | Change |
|---|---|
| `AdminPhoto.user` (`PhotoUser`) | + `auto_banned` |
| `POST /api/admin/users/{id}/uploads` → `user` | now the full `AdminUser` (+ `auto_banned`, `auto_ban`), like every other admin user object |
| event `user.uploads_changed` → `users[]` | full `AdminUser` (+ `auto_banned`, `auto_ban`) |
| event `user.created` | + `instagram`, `auto_banned` (`{id, name, instagram, banned, auto_banned, uploads_paused}`) |
| `GET /api/admin/instagram` → `handles[].users[]` | + `auto_banned` |
| `POST /api/join` (201, new guest) | + `instagram_kept: false` (was only sent on 200) |
| `GET /api/admin/photos` `next`, `GET /api/admin/users` `next_offset`, `GET /api/admin/audit` `next` | `null` when nothing follows, also when the page is exactly full (was: the cursor, costing one empty fetch) |
| every `/api/admin/*` answer | header `X-VB-Event-Id: <epoch>-<n>`: the event stream's position before the request read anything (see §4) |
| `POST /api/admin/login` 429 `login_locked` | + `Retry-After` |
| `PATCH /api/me` for a banned device | still 403 `banned`, message now "Dieses Gerät ist gesperrt." (uploads keep "Dieses Gerät wurde für Uploads gesperrt.") |
| 405 answers | + `Allow` header |
| `POST /api/x/{ext}/upload` | unchanged JSON; typed as `UploadOut`: `photo` + the extensions' fields (`beer_number`, `total`, `booth_number`), each optional in the schema (only the uploading extension's are sent) |
| `GET /api/x/beer/stats` | + `next_number`: the next beer's own number (its `seq`, like the Fotobox's `next_number`); `total` stays the board (visible beers) |

All admin user objects are `AdminUser` now (one shape): `auto_banned` is true
when the guest is banned only because it joined showing a banned fingerprint;
`auto_ban` names that fingerprint ban (`fp_hash`, `source_user_id`,
`source_user_name`) while it exists, else `null`. `UserRef` =
`{id, name, instagram, banned, auto_banned}`.

## 3. Errors

Every error is `ErrorBody {error: ErrorCode, message: string}`; `message` is
German and shown as-is. `ErrorCode` (source: `backend/src/virtubooth/core/errors.py`,
also the `ErrorBody.error` enum in the schema):

| Code | Status | Where |
|---|---|---|
| `scan_qr` | 404 | no party access (any access-gated route) |
| `needs_consent` | 401 | not joined yet |
| `banned` | 403 | banned device |
| `consent_outdated` | 409 | join with an old consent version |
| `invalid_instagram` | 400 | join, `PATCH /api/me` |
| `uploads_paused`, `uploads_stopped` | 403 | upload |
| `unsupported_type` | 415 | upload (not `image/jpeg`) |
| `too_large` | 413 | upload ("Das Bild ist zu groß.") or any JSON body > 64 KiB ("Anfrage zu groß.") |
| `invalid_meta`, `empty_upload`, `invalid_image` | 400 | upload |
| `admin_required` | 401 | admin routes |
| `wrong_password` | 401 | login |
| `login_locked` | 429 + `Retry-After` | login: 5 per minute / 20 per hour per IP (IPv6 per /64); after 20 failures in 15 min from anywhere, every login (the right password too) for 5 min. Direct loopback is exempt (wave 4, SEC-01) |
| `invalid_filter`, `invalid_cursor` | 400 | admin lists |
| `no_fingerprint` | 400 | ban with `fingerprint: true` |
| `restore_required` | 400 | `POST /api/admin/upload-pause {enabled: false}` |
| `bad_origin` | 403 | CSRF check (every POST/PUT/PATCH/DELETE) |
| `length_required` | 411 | chunked or unparsable Content-Length |
| `rate_limited` | 429 + `Retry-After` | budgets (API, join, upload, login) |
| `invalid_request` | 422 | request validation |
| `not_found` | 404 | unknown photo/guest/extension/device ban, `/media` |
| `http_404`, `http_405` | 404, 405 | unknown `/api` path, wrong method |

`network`/`timeout` stay client-only codes. Each route declares its error
statuses in the schema (router-level `responses=`), all with `ErrorBody`.

## 4. The admin event stream (`GET /api/admin/events`)

- Server-Sent Events. First `retry: 3000`, then per event
  `event: <type>` / `data: <JSON>` / `id: <epoch>-<n>`; `: ping` after 15 s idle.
  `Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`.
- Schema: `AdminEvent`, a union discriminated by `type`. Each variant is
  `{type, id, data}`: the SSE message with `data` parsed. On the wire `data`
  is the payload alone (as before), `id` the SSE id, `type` the SSE event name.
- Event types and payloads (unchanged except §2): `photo.created`,
  `photo.hidden`, `photo.unhidden` `{photo}`; `photo.deleted` `{id, photo|null}`;
  `user.created`; `user.banned`, `user.unbanned` `{user, photos}`;
  `fingerprint.banned` `{fp_hash, user_id}`; `fingerprint.unbanned` `{fp_hash}`;
  `user.uploads_changed` `{users, paused}`; `settings.upload_stop` `{upload_stop}`;
  `settings.upload_pause` `{upload_pause, restored, kept}`.
- New: `stream.resync` `{reason: "gap" | "restart"}` (no id): the server can't
  replay what the client missed; refetch everything.
- Ids are `<epoch>-<n>`; the epoch changes with every server start.
- Resuming: the browser sends `Last-Event-ID` on its automatic reconnects; the
  server replays the missed events (it keeps the last 1024) or sends
  `stream.resync`. For the first connect, pass the `X-VB-Event-Id` header of
  the page's first admin fetch as `?since=<id>`: nothing that happened between
  that fetch and the stream is lost (this fixes the old gap).
- The stream ends (and EventSource reconnects by itself) when the session is
  gone (logout closes that session's streams at once; expiry is checked at
  most every 30 s; the reconnect then gets 401), when the client falls 256
  events behind (the reconnect replays them), or when the session opens a
  fifth stream (at most 4 per session; the oldest closes; wave 4, SEC-06). An
  ended stream is normal: reconnect, don't show an error.

Suggested client (`useAdminEvents`): fetch → read `X-VB-Event-Id` → open
`EventSource('/api/admin/events?since=' + id)` → on `stream.resync` invalidate
all admin queries → on error keep today's behaviour (check
`/api/admin/session`, poll every 5 s while down).

## 5. Pages and files

HTML is no longer part of the API package: see `web-serving.md`. Gone:
`/static/*`, `/admin/assets/*`, and files under `/x/<id>/` (those paths are
now app routes that return `index.html`).

## 6. Exports and the Instagram board (wave 2, BE-features)

Owner: BE-features. PLAN §3 "New endpoints" items 2–3. All routes are admin
routes: admin session, CSRF origin check on mutations, `X-VB-Event-Id` on every
answer (the file downloads included), `ErrorBody` errors. Export creation needs
no budget of its own: admin sessions are exempt from the API budgets.

### 6.1 Endpoints

| Route | Answer |
|---|---|
| `GET /api/admin/exports` | `ExportJobsOut {jobs: ExportJob[], public_base_url: string \| null, ffmpeg: bool}`. Jobs newest first. `public_base_url` = `VB_PUBLIC_BASE_URL` (prefill for the QR form), `ffmpeg` = timelapse jobs can run. |
| `POST /api/admin/exports` | Body `ExportIn {kind, options?}` (a union discriminated by `kind`). New job: **202** `ExportCreatedOut {job, created: true}`. A job of the same kind already queued or running: **200** `{job: <that job>, created: false}`; nothing new is queued and the request's options are ignored. 400 `base_url_required` / `invalid_base_url` (qr), 422 `invalid_request` (unknown kind or option, out-of-range value). |
| `GET /api/admin/exports/{id}/download` | The file as an attachment: `application/zip` (archive, qr) or `video/mp4` (timelapse), `Content-Disposition: attachment; filename="<file_name>"`, Range requests work. 409 `export_not_ready` while queued or running ("Der Export ist noch nicht fertig.") or when it failed; 404 `not_found` for an unknown id or a file that is gone. |
| `DELETE /api/admin/exports/{id}` | `ExportDeletedOut {ok: true, id}`: record and file are gone. Deleting a **queued** job cancels it. 409 `export_running` while it runs; 404 `not_found`. |
| `GET /api/admin/instagram` | unchanged, plus `done: bool` per handle. |
| `POST /api/admin/instagram/{handle}/done` | Body `{done: bool}` → `InstagramDoneOut {handle, done, changed}`. `handle` is normalized like the guests' input (lower case, leading `@` dropped, so `@Anna.Party` = `anna.party`); the answer has the normalized one. 400 `invalid_instagram`, 404 `not_found` when no guest gave that handle. `changed: false` when it already was in that state (no audit entry, no event). |
| `GET /api/admin/instagram/{handle}/photos.zip` | A zip, streamed: `Content-Disposition: attachment; filename="fotos-<handle>.zip"`. Entries `0001-<activity>-<photo id>.jpg`, … in upload order (stored, not deflated): the handle's photos that are not hidden and not deleted, of guests who are not banned (a banned guest's photo stays out even when an admin un-hid it). 404 `not_found` when there is none, 400 `invalid_instagram`. |

Ids of export jobs are server-generated (`[A-Za-z0-9_-]{16}`, the shape of
photo ids; anything else is 422). Downloads only ever serve files directly in
`<data>/exports/`.

### 6.2 `ExportJob`

```
{id, kind: "archive" | "timelapse" | "qr",
 status: "queued" | "running" | "done" | "failed",
 progress: number | null,      // null while queued, 0..1 while running, 1 when done,
                               // a failed job keeps its last value
 created_at, started_at, finished_at,   // ISO-8601 UTC; null until reached
 error: string | null,         // German, shown as-is (failed jobs)
 file_name: string | null,     // set when done, e.g. "archiv-20261013-2215-AbC_x-9z.zip"
 bytes: number | null,         // set when done
 download_url: string | null,  // "/api/admin/exports/<id>/download" when done
 options}                      // what it runs with, defaults filled in (qr: the URL used)
```

Options (all optional; unknown keys are 422):

| kind | options (default) | output |
|---|---|---|
| `archive` | `include_hidden` (false), `include_db` (false) | `archiv-<YYYYMMDD-HHMM>-<id8>.zip`, one top folder named like the file: `photos/<activity>/<seq>_<file>.jpg` (hidden ones under `photos/<activity>/hidden/`), `photos.csv`, `users.csv`, `instagram.csv` (as the CLI export), `manifest.json` (`format: "virtubooth-archive/1"`, party name, options, counts, one entry per photo with its `file`), `README.txt`, and with `include_db` `virtubooth.db`: a consistent copy made with SQLite's backup API (never the live file), with `admin_sessions` and `export_jobs` emptied and vacuumed (wave 4, SEC-03). |
| `timelapse` | `extension` ("beer", an activity id), `fps` (12, photos per second, 1–30), `crossfade` (false), `include_hidden` (false) | `zeitraffer-<extension>-<YYYYMMDD-HHMM>-<id8>.mp4`: H.264, 1080×1440, the last photo held 2 s, as `python -m virtubooth.tools.timelapse` makes it. With `crossfade` the video runs at 30 fps (60 when `fps` is 30). |
| `qr` | `base_url` (`VB_PUBLIC_BASE_URL`; neither → 400 `base_url_required`, malformed → 400 `invalid_base_url`) | `qr-codes-<YYYYMMDD-HHMM>-<id8>.zip`, one top folder: `qr-sheet.html` (self-contained: inline CSS and SVG, no scripts, no external files; party name on it; one A4 page per code) plus `qr-home.svg/.png` and `qr-<activity>.svg/.png` for every activity on the home page. The codes carry the party token. |

A job fails (status `failed`, German `error`) for example when ffmpeg is
missing ("Für den Zeitraffer fehlt ffmpeg auf dem Server. …"), when the
activity has no (visible) photos, when the disk is too full, or with
"Server wurde neu gestartet." (see 6.4). Anything unexpected: "Der Export ist
fehlgeschlagen. Details stehen im Server-Log."

### 6.3 Errors and events added

| Code | Status | Where |
|---|---|---|
| `export_not_ready` | 409 | download of a queued, running or failed job |
| `export_running` | 409 | delete of a running job |
| `base_url_required` | 400 | qr job without `base_url` and without `VB_PUBLIC_BASE_URL` |
| `invalid_base_url` | 400 | qr `base_url` not `http(s)://host[/path]` or with `?`/`#` |

Admin events (in the `AdminEvent` union):

- `export.updated {job: ExportJob}`: created (queued), started (running),
  progress (at most every 5 % or every second), done, failed.
- `export.deleted {id}`: deleted by an admin, or pruned (6.4).
- `instagram.done {handle, done}`: the mark changed.

Audit vocabulary: `export.create` / `export.delete` with target
`export:<id>` (details: kind and options / kind, status and file name);
`instagram.done` / `instagram.undone` with target `instagram:<handle>`.
Each is written in the same transaction as the change.

### 6.4 Runtime and persistence (decision)

- **Job state lives in a new table `export_jobs`** (migration step 3, appended
  to `db.MIGRATIONS`), not in the settings KV: jobs are a list of records whose
  status and progress a worker thread updates, the worker claims the oldest
  queued job atomically (`UPDATE … WHERE status='queued'`), and deleting a
  queued job must race safely with that claim. The KV holds small singleton
  JSON values and would need a read-modify-write of one blob per progress
  step. The Instagram marks, a small set, do live in the KV
  (`settings.instagram_done = {"handles": {<handle>: {at, by}}}`).
- One worker thread runs the jobs one at a time, oldest first. It starts and
  stops with the app's lifespan; stopping cancels the running job.
- On start, jobs left `queued` or `running` become `failed` with
  "Server wurde neu gestartet." (their partial files are removed).
- At most one queued or running job per kind (see `POST` above).
- Files go to `<data>/exports/` (written as `.<id>.part`, renamed when done;
  scratch dirs `.vb-job-<id>-*` there too, never `/tmp`). The newest 10 done
  jobs keep their files; older done jobs are deleted with their file
  (`export.deleted`). The newest 10 failed records are kept.
- The CLI tools (`python -m virtubooth.tools.qr|timelapse|export`) are
  unchanged and still write their own files next to these.

### 6.5 For the admin UI

- Start: `POST /api/admin/exports` with `{kind, options}`. Read `created`
  (or the status code) to tell "started" from "already running".
- Progress: listen for `export.updated` on the event stream you already have
  and replace the job by `id`; `export.deleted` removes it. Without the
  stream, poll `GET /api/admin/exports` (e.g. every 2 s while any job is
  `queued` or `running`).
- Download: a plain link to `download_url` (`<a href download>`); it is a GET
  with the admin cookie, so no CSRF header is needed. The same for the
  Instagram zip: `/api/admin/instagram/<handle>/photos.zip`.
- QR form: prefill `base_url` with `public_base_url`; when that is null the
  field is required (else 400 `base_url_required`). Timelapse form: disable it
  with a hint when `ffmpeg` is false; `fps` 1–30 (default 12).

## 7. The dashboard: join stop and live overview

The admin home (Live) and the manage header show two one-tap switches side by
side, „Hochladen stoppen“ (the existing upload stop, §4 `settings.upload_stop`)
and „Anmeldung stoppen“ (new), plus a status strip while either is on. All
routes below are admin routes (session, CSRF on mutations, `X-VB-Event-Id`).

### 7.1 Join stop („Anmeldung stoppen“)

| Route | Answer |
|---|---|
| `GET /api/admin/join-stop` | `StopState {enabled, since, by}` (the upload stop's shape) |
| `POST /api/admin/join-stop` | Body `StopIn {enabled}` → `StopOut {enabled, since, by, changed}`. `changed: false` when it already was in that state (no audit entry, no event). |

- Persisted in the settings KV (`join_stop = {enabled, since, by}`), so it
  survives a restart. Audit: `join.stop` / `join.resume`. Event:
  `settings.join_stop {join_stop: StopState}`.
- While on, `POST /api/join` from a device without a guest gives **403
  `join_closed`** „Gerade kann niemand neu beitreten. Versuch es gleich noch
  mal.“ (before the consent-version check and the join budget). A device that
  joined already is not affected: identify, a second tab's join (200),
  uploads (they follow the upload switches only).
- `POST /api/identify` for an unknown device adds `join_closed: bool` to
  `NeedsConsentOut`. The join sheet then shows a calm message instead of the
  button and re-identifies on focus, visibility, every 15 s and on „Nochmal
  versuchen“.

### 7.2 Visitor ids and last-seen times

- **`vb_vid` cookie**: a random id (`secrets.token_urlsafe(12)`), signed like
  `vb_uid`, HttpOnly, SameSite=Lax, Secure as the other cookies, 30 days. Set
  at the token entry (`?t=`, the 303) when the browser has none, and at
  `identify`/`join` for browsers from before this change.
- **`visitors` table** (migration v4): `id, first_seen_at, last_seen_at,
  user_id`. Only random ids and timestamps, no IP, no user agent. `join` (and
  `identify` of a known guest) links the visitor to its guest; a link is never
  removed.
- **Last seen**: every guest API route (`require_access`) refreshes
  `users.last_seen_at` (joined) or `visitors.last_seen_at` (not joined), at
  most once per device and 60 s (an in-memory throttle; one small `UPDATE`).
- **Archive**: the database copy in an archive export empties `visitors`
  (`SCRUBBED_TABLES`, with `admin_sessions` and `export_jobs`): browser ids are
  live-dashboard data with no value after the party.

### 7.3 `GET /api/admin/overview`

`OverviewOut {at, active_minutes, guests, scans, photos, activities}`. The UI
polls it every 10 s while the page is visible and refetches it (throttled) on
`photo.*`, `user.created|banned|unbanned|uploads_changed` and
`settings.upload_pause`. "Now" is the last `active_minutes` (5) minutes.

| Field | Definition |
|---|---|
| `guests.total` | every guest (device) that joined |
| `guests.active_now` | not banned, last seen (any guest API request) in the last 5 min |
| `guests.uploading_now` | distinct guests with an upload in the last 5 min |
| `guests.instagram`, `.banned`, `.paused` | guests with a handle; banned; uploads paused (by hand or the new-guest pause) |
| `scans.scanned` | visitor ids: browsers that opened a valid QR link |
| `scans.joined` / `scans.not_joined` | of those, linked to a guest / never joined (`scanned − joined`) |
| `scans.waiting_now` | not joined, seen in the last 5 min |
| `scans.since` | the first visitor's `first_seen_at` (counting starts with v4), or null |
| `photos.total`, `.visible`, `.hidden` | photos not deleted |
| `photos.last_15_min`, `.last_60_min` | uploads received in that window, including ones hidden or deleted since |
| `photos.last_upload_at` | the newest upload (any) |
| `activities[]` | `{id, title, photos, visible, last_60_min}` per loaded photo activity, plus ids only old photos have |

Guests from before v4 have no visitor row until their browser comes back
(then `identify` creates one, linked), so right after the update
`scans.scanned` can be lower than `guests.total`.
