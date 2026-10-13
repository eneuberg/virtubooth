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
| `login_locked` | 429 + `Retry-After` | login |
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
  gone (checked at most every 30 s; the reconnect then gets 401) or when the
  client falls 256 events behind (the reconnect replays them). An ended stream
  is normal: reconnect, don't show an error.

Suggested client (`useAdminEvents`): fetch → read `X-VB-Event-Id` → open
`EventSource('/api/admin/events?since=' + id)` → on `stream.resync` invalidate
all admin queries → on error keep today's behaviour (check
`/api/admin/session`, poll every 5 s while down).

## 5. Pages and files

HTML is no longer part of the API package: see `web-serving.md`. Gone:
`/static/*`, `/admin/assets/*`, and files under `/x/<id>/` (those paths are
now app routes that return `index.html`).
