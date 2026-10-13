# Security review of the overhaul (branch `ov/sec`, waves 1 + 2)

Reviewer: independent security agent, 2026-10-13. Report only: no code was changed.

**Scope.** The whole delta `main...HEAD`, plus a fresh check of the core auth model:
- the backend under `backend/src/virtubooth`;
- the new React frontend and its build (`frontend/`, `dist`);
- exports, the Instagram board and the event-stream replay;
- web serving, Docker and config.

**Method.** Code read end to end, then live tests against a throwaway server on
`127.0.0.1:8200` with a temp data dir and `gen-env` secrets, running the built `frontend/dist`.
- Every "confirmed" finding below was reproduced against that server.
- The repro snippets use small httpx helpers: `access()` follows the `?t=` entry, `join()`
  joins as a guest, `admin()` logs in.
- `X-Forwarded-For` stands in for distinct client addresses: the default
  `--forwarded-allow-ips` trusts 127.0.0.1, like a reverse proxy on the same host.

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | |
| High | 0 | |
| Medium | 1 | SEC-01 |
| Low | 5 | SEC-02 … SEC-06 |
| Info | 9 | SEC-07 … SEC-15 |

The core model holds:
- party-token gate;
- signed cookies;
- admin sessions;
- CSRF origin check;
- body caps;
- media access control;
- upload validation.

All 28 `/api/admin/*` routes refuse anonymous and guest callers. Nothing in the new
export, Instagram or SSE code allows path traversal, injection or access without a session.

The one Medium finding is about login brute-force resistance. The global "lockout" never
stops a guess from being checked, and the per-IP buckets key on the full IPv6 address.

## Findings

### SEC-01 · Medium · confirmed: the login lockout does not stop distributed guessing

**Affected code**
- `backend/src/virtubooth/services/admin_auth.py:44-67`
- `backend/src/virtubooth/core/ratelimit.py:82-84`
- `backend/src/virtubooth/core/security.py:125-128` (`client_ip`)

**Description.** Login runs these steps in order:
1. It charges `login_ip` (5/min) and `login_ip_hourly` (20/h), keyed on the exact client address.
2. It **always** compares the password.
3. Only for a wrong password does it consult the global failure bucket (50/h). When that
   bucket is empty, a wrong guess gets `429 login_locked` instead of `401`, but the correct
   password still gets `200` and a session.

So the global bucket changes the status code of wrong guesses and nothing else. It slows no
one down. The per-IP buckets are the only real throttle. They key on the full address, so
one IPv6 /64, a botnet or a proxy pool gets unlimited fresh buckets. The middleware API
budget (`api_ip`) has the same per-address keying.

**Repro** (`t16_login.py`):
```python
def login(pw, ip):
    r = c.post("/api/admin/login", json={"password": pw}, headers={"X-Forwarded-For": ip})
    return r.status_code, r.json().get("error"), r.headers.get("retry-after")
[login("wrong-password-x", "198.51.100.7") for _ in range(7)]
#   -> 5x (401 wrong_password), then (429 rate_limited)          per-IP limit works
[login("wrong-password-x", f"2001:db8:1:2::{i:x}") for i in range(1, 61)]
#   -> 44x (401 wrong_password), 16x (429 login_locked, Retry-After 72)
login(PASSWORD, "2001:db8:1:2::ffff")
#   -> (200, None, None)     the right guess still logs in while "locked", same /64
```

**Impact.**
- The admin password is the only thing between the internet and every guest's photos,
  their IPs and fingerprints, bans, and the DB copy in the export.
- `gen-env` (120 bit) and Coolify's generated passwords are safe.
- A host-chosen password that only meets the 12-character minimum ("Sommerfest2026") can
  be dictionary-attacked at network speed from one IPv6 prefix.

**Recommended fix**
1. Key the per-IP login (and API) buckets on the /64 for IPv6:
   ```python
   ip = ipaddress.ip_address(host)
   key = str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else host
   ```
2. Make the global lock real. While `login_failures_global` is exhausted, refuse **every**
   login, correct passwords included, with `429 login_locked` + `Retry-After`. Shorten the
   window (for example 20 failures per 15 min) so a lockout costs the host minutes, not an
   hour. To keep the "anyone can lock the admin out" concern manageable:
   - let logins from loopback or a `VB_ADMIN_LOGIN_ALLOW` CIDR bypass the lock;
   - or document "restart the container to clear the lock" (the buckets live in memory).
3. Raise the password minimum to 16 characters, or reject passwords without enough
   character classes. Mention `gen-env` in the error message.
4. Add a test: correct password + exhausted global bucket → 429.

### SEC-02 · Low · confirmed: re-encoding keeps the JPEG comment (COM) segment

**Affected code:** `backend/src/virtubooth/services/images.py:62-67` (`img.save(...)`, `img.copy()`)

**Description.** The module promises that re-encoding "drops every byte the client chose".
Pillow ≥ 9.4 writes `im.info["comment"]` back on save by default, and `img.copy()` carries
it into the thumbnail. EXIF, GPS, XMP, ICC and trailing bytes are dropped. Up to 64 KB of
client-chosen bytes survive in both stored files, in `/media` answers, in the archive and
in the Instagram zips.

**Repro** (`t8_meta_strip.py`): upload a 1080×1440 JPEG saved with
`comment=b"<script>alert(1)</script> COMMENT-MARKER" + b"A"*2000`, EXIF GPS, XMP, ICC and
trailing bytes, then fetch it back:
```
full  stored meta: {'comment': 2041} | COMMENT-MARKER: True | GPS: False | trailing: False | EvilCam: False
thumb stored meta: {'comment': 2041} | COMMENT-MARKER: True | GPS: False | trailing: False | EvilCam: False
```

**Impact.** Low. The files are served as `image/jpeg` with `nosniff` and the CSP, so the
bytes cannot be executed in the app. Still:
- the "nothing the client chose survives" guarantee is false;
- arbitrary data rides along into exports and onto Instagram uploads (Instagram re-encodes,
  other targets may not);
- the README says EXIF/GPS are stripped, which stays true, but comment fields from other
  tools leak.

**Recommended fix.** Drop all metadata before both saves. This was verified to remove the
marker:
```python
img = ImageOps.exif_transpose(img).convert("RGB")
img.info.clear()          # no comment, exif, xmp, icc carried into save()
...
thumb_img = img.copy()    # inherits the empty info
```
Add a regression test that uploads a JPEG with `comment=` and asserts that `b"MARKER"` is
not in either stored file.

### SEC-03 · Low · confirmed: the archive's database copy contains admin sessions; free pages are not scrubbed

**Affected code**
- `backend/src/virtubooth/tools/export.py:82-122` (`snapshot_db`, `take_snapshot`)
- `backend/src/virtubooth/services/export_runners.py:121-122`
- README text `tools/export.py:268-274`

**Description.** With `include_db`, the zip contains a full SQLite backup, including:
- `admin_sessions`: each session's SHA-256 token hash, `pw_tag`, the admin's IP and user
  agent, and its expiry;
- `export_jobs`;
- `settings`.

The archive README (and the option's description) list IPs, fingerprints and the audit log,
but not admin session data. SQLite's backup API also copies free pages, so rows deleted
earlier can be recovered from the copy.

**Repro** (`t14_exports.py`): `POST /api/admin/exports {"kind":"archive","options":{"include_db":true}}`,
download the file, open `virtubooth.db`:
```
tables: users, user_fingerprints, fingerprint_bans, photos, admin_sessions, audit_log, settings, export_jobs
admin_sessions rows: [('b317c98d…', 'KMlnmWpsLZTNG-axuWI_e6', '203.0.113.9', 'python-httpx2/2.13.1', '2026-10-13T18:46:37…'), …]
```

**Impact.** Low. Neither value can be turned into a session:
- the token hash is SHA-256 of 256 random bits;
- `pw_tag` is an HMAC keyed with `VB_SECRET_KEY`.

But the archive is meant to be handed around after the party. It should not carry live
session records and admin IPs, and the docs under-describe what is inside.

**Recommended fix.** In `take_snapshot`, after the copy:
1. Run `DELETE FROM admin_sessions;` and optionally `DELETE FROM export_jobs;`.
2. Run `VACUUM` on the snapshot so free pages are rewritten. Alternatively use
   `PRAGMA secure_delete=ON` before the deletes.
3. List exactly what the copy contains in the README and in the `include_db` field
   description.

### SEC-04 · Low · confirmed: the CSRF origin check ignores the scheme

**Affected code:** `backend/src/virtubooth/core/security.py:150-167` (`origin_allowed`)

**Description.** Only the netloc of `Origin`/`Referer` is compared with `Host`.
`Origin: https://host` is accepted on an http deployment, and `Origin: http://host` on an
https one. A page served from `http://party.example` therefore passes the check for
`https://party.example`.

**Repro** (`t4_csrf.py`, live, admin session + guest cookies):

| Header | Result |
|---|---|
| none / `null` / `https://evil.example` / `http://127.0.0.1:8200.evil.example` / evil Referer | 403 `bad_origin` on every mutation |
| `Origin: https://127.0.0.1:8200` (server is http) | accepted: export created (202), Instagram mark (200), upload-stop (200), `PATCH /api/me` (200) |

**Impact.** Low. Exploiting it needs all of the following:
- an active network attacker who can answer for `http://party.example` (for example on the
  venue Wi-Fi);
- a browser that does not apply schemeful same-site (Firefox and Safari today);
- no HSTS pin yet for the host.

Even then, only CORS-simple requests get through. Those are body-less POSTs: photo
hide/unhide, unban, logout. JSON bodies and `image/jpeg` trigger a preflight that fails.
HSTS is sent on https answers, which shrinks the window.

**Recommended fix.** Compare the full origin. When `VB_PUBLIC_BASE_URL` is set, accept
exactly its `scheme://host[:port]`, plus `allowed_origins`. Otherwise derive the scheme from
`request.url.scheme`, which honours a trusted `X-Forwarded-Proto`:
```python
expected = f"{request.url.scheme}://{_normalize_netloc(host, request.url.scheme)}"
return f"{parts.scheme}://{_normalize_netloc(parts.netloc, parts.scheme)}" == expected
```
Keep accepting the http/https mismatch only when the operator opts in, for proxies that
don't forward the protocol.

### SEC-05 · Low · confirmed: precompressed HTML entries bypass the gate as public root files

**Affected code:** `backend/src/virtubooth/web/frontend.py:212-221` (`public_file`)

**Description.** `public_file` refuses names ending in `.html` but serves every other root
file. `scripts/precompress.mjs` writes `index.html.br/.gz`, `admin.html.br/.gz` and
`gate.html.br/.gz` into the root of `dist`. They are served without the access cookie, as
`text/html` without `Content-Encoding`, with `Cache-Control: public, max-age=300`.

**Repro** (`t12_web.py`):
```
GET /index.html      -> 404 gate
GET /index.html.gz   -> 200 OK  (gzip of the guest app shell)   no cookie
GET /index.html.br   -> 200 OK
GET /admin.html.gz   -> 200 OK
```

**Impact.** Low. Only the app shell leaks, and it references bundles that are public under
`/assets` anyway. But it breaks the contract "pages without access get the gate", and any
future build step that puts something sensitive into an HTML entry would leak through this.

**Recommended fix.** In `public_file`, refuse names whose base (after stripping `.br`/`.gz`)
ends in `.html`, or refuse `.br`/`.gz` in the root altogether. Even better, serve only an
explicit allow-list: `boot-check.js`, `gate-hint.js`, `icon.svg`. Alternatively stop
`precompress.mjs` from writing siblings for root HTML files. The server never uses them;
it renders the HTML itself.

### SEC-06 · Low · confirmed: the event stream outlives logout by up to 45 s; no cap on streams per session

**Affected code:** `backend/src/virtubooth/api/routers/admin/events.py:183-227`

**Description.** The session is re-checked only when `now - checked >= 30 s`. The loop
wakes at most every 15 s, so a revoked session keeps receiving every admin event (AdminUser
objects with IPs, fingerprints and user agents) for up to about 45 s. Nothing limits how
many streams one session opens. Each holds a 256-slot queue and a task.

**Repro** (`t7_sse_revoke.py`): open `/api/admin/events`, `POST /api/admin/logout` with the
same cookie after 1 s → `stream ended after 45.0 s`.

**Impact.** Low. The window after logout is short, and only a holder of a valid admin
session can open streams.

**Recommended fix.**
1. Wake the stream immediately on logout. Keep a set of revoked session hashes, or publish
   an internal `session.ended` to the subscriptions of that `session_hash` (store it on the
   `Subscription`). Alternatively cut `SESSION_RECHECK_SECONDS` to 5 s and `_MAX_WAIT`
   to match.
2. Cap concurrent subscriptions, for example 8 per session hash and 64 in total. Answer the
   rest with `429`.

### SEC-07 · Info · confirmed: a percent-encoded `t` key is accepted as the token and logged unmasked

**Affected code**
- `backend/src/virtubooth/core/logs.py:8` (`_TOKEN_RE`)
- `backend/src/virtubooth/middleware.py:63-70`

**Repro:** `GET /?%74=<token>` → `303` + `vb_access` cookie. The access log shows
`"GET /?%74=NZoUpcLfxfJMPVpprmMqfUkm HTTP/1.1" 303`. The `?t=` form is masked as `t=***`.

**Impact.** Only a token holder can produce such a line, and the QR codes always use `?t=`.
This is defence in depth for the logs.

**Recommended fix.** Mask by parsing the query instead of a regex: replace the values of
every key that `parse_qsl` decodes to `t`. Or make the token entry accept only the literal
`t=` key.

### SEC-08 · Info: the Docker image bakes in `VB_DEV=1` (re-check after INT-A)

**Affected code:** `Dockerfile` (ENV block, `VB_DEV=1` + TODO)

`VB_DEV` only changes one thing: a missing web dir serves placeholders instead of refusing
to start. That was verified with grep: the only use is `web/frontend.py:128`. It relaxes
nothing in security. On the branch, though, a production image whose `VB_WEB_DIR` is wrong
starts silently with placeholder pages.

**Recommended fix.** Remove `VB_DEV=1` once the Node stage ships `/app/web` (INT-A is
changing the Dockerfile in parallel). Re-check that the merged image:
- still runs as `USER 10001:10001`;
- has no `.env` in the build context;
- keeps `.dockerignore` as an allow-list.

### SEC-09 · Info: cookie-dependent HTML is `no-cache`, not `private`

`/`, `/x/*` and `/admin/*` answer differently with and without cookies (app vs gate, app vs
303), but send `Cache-Control: no-cache` without `Vary: Cookie`. The origin never answers
304, so a shared cache cannot serve a stored copy without revalidating. Today that is safe.

**Recommended fix.** `private, no-cache` for HTML entries and the gate, and `no-store` on
the `?t=` 303 (it carries `Set-Cookie`).

### SEC-10 · Info: the fingerprint is fully client-controlled (evasion, row growth, ban poisoning)

**Affected code:** `services/identity.py:137-162`, `repositories/users.py:84-106`

This is known and by design ("hint only"), but the overhaul did not change it, so it is
recorded here:
- A new hash evades a device ban. Verified: rejoining with the same fingerprint gives
  `banned`, with another gives `ok`.
- Every `POST /api/identify` with a new hash adds a `user_fingerprints` row. That is up to
  300 per minute per device under the API budget, which bloats the user page.
- A guest who sets its current hash to a common device's hash before being banned "with
  device" auto-bans every new guest on that device model.

**Recommended fix.**
- Cap the fingerprint rows per user (for example 20; update `last_seen` on the oldest
  instead).
- In the ban sheet, show `shared_with` before banning a fingerprint (the data is there).

### SEC-11 · Info: `uid_token` has no expiry

`Signer.sign("uid", public_id)` carries no timestamp. A copied `uid_token` (localStorage on
a shared phone) identifies the guest forever, until `VB_SECRET_KEY` rotates.
- Verified: a fresh browser with only the access cookie and a stolen token gets that
  guest's identity.
- A forged token gets `needs_consent`.

**Recommended fix (optional).** Sign `public_id|issued_at`. Accept tokens up to about 30
days old and re-issue on every identify.

### SEC-12 · Info · plausible: exports can fill the data volume

**Affected code**
- `services/exports.py:352-365`
- `services/export_runners.py:101`
- `tools/_common.py:355-364`

Up to 10 finished files are kept. Each archive is roughly as big as all photos (×1 with
hidden ones). `check_free_space` runs only for archives, and it leaves just 5 % + 10 MB
free. The timelapse writes its `.part` without any check.

An admin who exports repeatedly late in the party can fill the volume. Then uploads and
SQLite writes fail.

**Recommended fix.**
- Reserve headroom: refuse a job that would leave less than `max(1 GB, 10 % of the disk)`.
- Apply the check to timelapse jobs too, with a rough estimate of the mp4 size.
- Consider `KEEP_DONE = 3` for archives.

### SEC-13 · Info: supply chain

- Python: exact pins in `pyproject.toml`, and `uv.lock` has sha256 hashes for every
  artifact (46 packages, 807 hashes).
  - `httpx2`/`httpcore2` look unusual but are the pydantic-maintained fork that Starlette
    1.x's TestClient requires (metadata checked).
  - They are dev-only.
- Frontend:
  - exact versions (`savePrefix: ''`);
  - `pnpm-lock.yaml` with integrity hashes;
  - no package needs an install script (pnpm 11 blocks them; no `allowBuilds`);
  - no source maps in `dist`;
  - no secrets in the bundle (the only "SECRET" match is React's internal export name);
  - the `.vite/manifest.json` dotfile is not served.
- `minimumReleaseAgeExclude` exempts `vitest@5.0.4`, `@vitest/mocker@5.0.4`,
  `@vitest/spy@5.0.4` and **`zod@4.6.7`**, which is a runtime dependency that ships in the
  bundle. The exemption skips pnpm's 1-day quarantine against freshly compromised releases.
  The versions are locked by integrity hash, so the risk is limited to the moment of
  locking. **Recommended:** delete the four entries as soon as the versions are more than
  a day old, and treat future exemptions as a review item. The release dates could not be
  checked: no registry access from this sandbox.
- The `react-aria@3.53.1` patch was reviewed hunk by hunk. It only removes the two runtime
  `<style>` injections:
  - `usePress` `touch-action`: the rule is moved to `app.css`;
  - `usePreventScroll`: the injected style is replaced by a `data-vb-scroll-lock`
    attribute that `app.css` styles.

  No logic or nonce handling changes otherwise. Re-check it on every react-aria update.

### SEC-14 · Info · theoretical: decode cost of crafted progressive JPEGs

The exact 1080×1440 size check and `MAX_IMAGE_PIXELS` bound memory. The CPU time of a
progressive JPEG with very many scans inside the 8 MB limit is not bounded explicitly. Not
tested. Per-guest upload limits (10/min) and the thread pool limit the exposure.

**Optional hardening.**
- Lower `VB_MAX_UPLOAD_BYTES` for the two built-in activities: real 1080×1440 captures are
  well under 2 MB, so set `max_bytes=3_000_000` in their `UploadPolicy`.
- Run `process_jpeg` with a timeout.

### SEC-15 · Info: `VB_FORWARDED_ALLOW_IPS` is not validated

**Affected code:** `__main__.py:39-43`, `docker-compose.coolify.yaml`

`*` is accepted. The only warning is the help text and `.env.example`. With `*`, anyone who
reaches the port picks their own IP, which defeats every per-IP limit, including SEC-01's.
The Coolify compose trusts all of RFC 1918 by default. Any other container on Coolify's
shared Docker network could reach `app:8000` directly with a forged `X-Forwarded-For`.

**Recommended fix.**
- Refuse `*` at startup, or warn loudly.
- In the Coolify docs, suggest the proxy's network (for example the `coolify` bridge
  subnet) instead of all private ranges.

## Verified OK (coverage)

**Party-token gate and cookies**
- Token entry:
  - valid `?t=` → 303 to the same path without `t`, keeping other parameters, and sets
    `vb_access` (`HttpOnly`, `SameSite=Lax`, `Max-Age=2592000`, `Path=/`, `Secure` behind
    https);
  - invalid → 404 gate, no cookie;
  - not interpreted under `/api/`, `/admin`, `/assets/`, `/media/`, `/healthz`;
  - `HEAD`/`POST` with `t` are not entries.
- Open redirect: `//evil`, `///evil`, `/%2F%2Fevil`, `/%5Cevil`, `/%5C%5Cevil`, `/%09/evil`,
  `/%0D%0A/evil` and `/%2F%5Cevil` all redirect to a single-slash, same-site path
  (backslashes stay percent-encoded).
- Access log masking for `?t=` and `&t=` (except SEC-07). `/healthz` is filtered.
- Signing:
  - `vb_access` = HMAC of the token: rotating the token locks everyone out;
  - `vb_uid` = `public_id.HMAC`, with `Signer.unsign` refusing values over 256 characters;
  - forged and tampered uid tokens → `needs_consent`;
  - public ids are 96-bit random.
- Every secret comparison uses `constant_time_equals` (sha256 + `compare_digest`) or
  `compare_digest`.
- The gate and not-found pages are one static file (`data-vb-mode` occurs once; the rewrite
  is a fixed string replace with no request data, so no injection). The only difference is
  the requester's own access state (`X-VB-Page`).

**Admin auth**
- The password comes from env, has a minimum of 12 characters and is stripped.
- Sessions:
  - `token_urlsafe(32)`; only the sha256 is stored;
  - `HttpOnly`, `SameSite=Strict`, `Secure` behind https, `Max-Age` = session hours;
  - expired rows are swept on login;
  - a password change ends all sessions (`pw_tag`);
  - logout deletes the row.
- Login: the per-IP 5/min and 20/h limits answer `429 rate_limited` + `Retry-After`.
  `login_locked` carries `Retry-After` (but see SEC-01).
- **All 28 `/api/admin/*` routes**, enumerated from the live app's router tree including
  nested routers, answer `401 admin_required` with no cookie and with a guest-only cookie.
  Auth runs before body or path validation.
- Admin HTML: `/admin/<page>` without a session → 303 to
  `/admin/login?next=<quote(path?query)>`. The Location always starts with `/admin/login`.
- Frontend `safeNext` was tested with `//evil`, `/admin//evil`, `/admin/\evil`,
  `https://evil/admin/live`, `/admin/..%2f..`, a trailing newline and `#`: all fall back to
  `/admin/live`. Only `/admin/<name>[?safe-query]` is followed.

**CSRF**
- The middleware runs before routing for POST/PUT/PATCH/DELETE on every path. All of these
  get 403 `bad_origin` on all 8 sampled mutations, including the new exports `POST`/`DELETE`,
  Instagram `done`, `PATCH /api/me`, upload, logout and `PUT`:
  - a missing `Origin`/`Referer`;
  - `Origin: null`;
  - a foreign origin;
  - a look-alike host prefix;
  - a foreign `Referer`.
- `Sec-Fetch-Site` is not used. With the origin check plus `SameSite=Strict` on the admin
  cookie, that is fine.
- The frontend only uses `fetch`/XHR with `credentials: 'same-origin'`. With
  `Referrer-Policy: no-referrer`, browsers still send `Origin` on same-origin CORS-mode
  fetches.

**Guest identity**
- `POST /api/join` requires `accept: true`, the current `version` and a fingerprint.
  `new_user_ip` limits identities per IP.
- `PATCH /api/me`:
  - validates the handle (`^[a-z0-9._]{1,30}$`, no `..`, profile links, `@`, case, and the
    Kelvin sign folded to ASCII);
  - caps the body at 64 KiB (413), refuses chunked bodies (411);
  - answers 403 for banned guests.
- `GET /api/me/photos` takes no parameters (an extra `user_id` is ignored) and returns only
  the caller's visible photos. Guest B sees none of A's.
- Fingerprint components with `NaN`/`Infinity` are stored but serialised as `null` by the
  admin API. No 500, and SSE payloads go through `model_dump(mode="json")`.

**Uploads**
- `Content-Type` must be `image/jpeg` (parameters and case tolerated) → 415 otherwise.
- Magic bytes plus PIL format → PNG bytes refused.
- Exact 1080×1440 enforced server-side.
- `X-VB-Meta`:
  - at most 2048 characters;
  - must be a JSON object with known keys only;
  - beer `vessel` and booth `filter`/`facing` come from allow-lists.
- Size:
  - a declared `Content-Length` of 1 GB → 413 before reading;
  - a chunked 9 MB body → 413 by the streaming cap.
- EXIF, GPS, XMP, ICC and trailing bytes are stripped (see SEC-02 for the comment).
- Server-side enforcement verified live: paused → `uploads_paused`, stop → `uploads_stopped`,
  banned → `banned`. A banned guest's `PATCH /api/me` and `/api/me/photos` → 403.

**Exports**
- Job ids are `Path(pattern=…)`, so `..%2F`, `%2e%2e`, `%00`, `%0A`, a leading dot and short
  ids get 422 or 404.
- Downloads come only from `<data>/exports/<name>`: no `/`, no `\`, no leading dot, and the
  parent must equal the root after resolving.
- `Content-Disposition` names are server-generated from restricted characters.
- Archive entries are all `<root>/…`, with no absolute paths or `..`.
- ffmpeg:
  - is called as an argument list with no shell;
  - `extension` is regex-checked (`../etc` → 422) and never reaches the command line;
  - `fps` is limited to 1–30;
  - the preset is fixed.
- At most one queued or running job per kind; one worker. `.part` files and scratch dirs
  are cleaned up, including after a restart (no leftovers after the runs).
- The QR sheet HTML-escapes everything. `javascript:` and URLs with a query are refused.
  The token is only inside the codes.
- The audit log has `export.create`/`export.delete` and `instagram.done`/`instagram.undone`.
- CSV cells are protected against formula injection.

**Instagram**
- The path handle is normalised like guest input (`@Anna.Party`, `%40ANNA.PARTY` and
  ` anna.party ` all become `anna.party`).
- Traversal-like values give 404 (no route) or 400 `invalid_instagram`.
- The zip holds only photos that are not hidden and not deleted, from guests who are not
  banned. A banned guest's photo stays out even after an admin un-hides it.
- A `done` mark for an unknown handle → 404.

**SSE**
- Auth on connect: the router dependency answers 401 JSON.
- `since`/`Last-Event-ID`:
  - garbage, a foreign epoch, a negative or future id → `stream.resync`;
  - more than 64 characters → 422.
- History is bounded at 1024 events; queues at 256 with overflow drop.
- Replay can include events from before this session's login (all admins share one
  password and can read the same data over REST). That is acceptable.
- Payloads carry admin data (IPs, user agents, fingerprints) only to admins.

**Web serving**
- `/assets` traversal is refused, including `../`, `%2e%2e`, `%252e`, `..%5c`, `%5C`,
  `%00`, `//`, `%2F` and dotfiles (`.vite/manifest.json`).
- `.br`/`.gz` URLs → 404. Precompressed selection honours `q=0` and case.
- Cache headers:

  | What | Cache-Control |
  |---|---|
  | assets | `public, max-age=31536000, immutable` + `Vary: Accept-Encoding` |
  | `/api` (including SSE and file downloads) | `no-store` |
  | media | `private, max-age=86400` |

- **Security headers on every response type tested**: HTML 200, gate 404, not-found 404,
  303/308 redirects, assets, root files, API 200/401/403/404/405/422, media, healthz. That
  covers CSP (`script-src 'self'; style-src 'self'; … frame-ancestors 'none'`), `nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
  `Permissions-Policy: camera=(self), …`, and COOP/CORP same-origin. HSTS is present when
  the scheme is https (trusted `X-Forwarded-Proto`).
- `/media`:
  - an admin session, or access + the owner's `vb_uid`, is required (a uid cookie without
    access → 404; another guest → 404; anonymous → 404);
  - deleted photos → 404 for everyone;
  - hidden photos are served to the owner only (by design);
  - bad ids → 404.

**Frontend**
- No `dangerouslySetInnerHTML`, `innerHTML`, `insertAdjacentHTML`, `document.write`,
  `eval`, `new Function`, `window.open` or `postMessage` in `src/` or `public/`.
- Every `href` is built from server-generated ids or paths:
  - Instagram profile links use `encodeURIComponent` on a handle limited to
    `[a-z0-9._]` server-side, so no `javascript:`;
  - external links have `target=_blank rel="noopener noreferrer"`.
- Pseudonyms, handles, party name and join texts render as React text.
- Storage:

  | Where | What |
  |---|---|
  | localStorage | `vb_uid` (the uid token, by design), `vb_join_text` (the accepted texts), activity preferences |
  | sessionStorage | `vb_debug`, `vb_debug_folded`, the reload flag, the in-app hint |
  | IndexedDB `vb-booth/outbox` | the guest's own pending JPEGs and meta |

- The `?debug` overlay shows error messages and the first 12 hex characters of the
  fingerprint hash, as text only. It reveals nothing beyond the device's own state.
- `boot-check.js` and `gate-hint.js` are ES5 DOM-only (no `innerHTML`, no inline styles);
  `gate-hint` only reads `navigator.userAgent`.
- `dist` has no source maps and no secrets.

**Config**
- `Settings` requires:
  - a token of 16–128 characters of `[A-Za-z0-9_-]`;
  - a password of at least 12 characters (see SEC-01);
  - a secret of at least 32 characters;
  - `cookie_secure` ∈ auto/true/false.
- `allowed_origins` entries are compared exactly (a `*` never matches).
- The app warns when cookies are not Secure but the public URL is https.
- `VB_DEV` relaxes nothing in security (it only selects placeholder pages).
- `gen-env`: token 144 bit, password 120 bit, secret 384 bit (`secrets.token_urlsafe`).
- The Dockerfile on this branch still runs as uid 10001. The compose files keep
  `read_only`, `cap_drop: ALL`, `no-new-privileges` and a localhost-only published port
  (re-check after INT-A, SEC-08).

## Top recommendations

1. **SEC-01:** make the login lockout bind the correct password too, with a short window
   and a loopback/allow-list escape. Key IPv6 limits on the /64. Raise the password minimum.
2. **SEC-02:** add `img.info.clear()` before both saves in `process_jpeg`, plus a test.
3. **SEC-03:** scrub `admin_sessions` and `VACUUM` the snapshot before it goes into the
   archive. Document the contents.
4. **SEC-04 / SEC-05:** compare the full origin (scheme too). Serve only an allow-list of
   root files.
5. Before release: remove `VB_DEV=1` from the image, drop the `minimumReleaseAgeExclude`
   entries once aged, refuse `VB_FORWARDED_ALLOW_IPS=*`.

## Resolution

Security-fix agent (wave 4), branch `ov/secfix`, 2026-10-13. One commit per
finding (two pairs share one); the regression tests are in
`backend/tests/api/test_security_fixes.py`, one section per finding.

**Verification**
- Backend: `uv run pytest -q` → 502 passed, 1 skipped (86 new tests; 8 existing
  tests adapted to the new behaviour). `ruff check`, `ruff format --check` and
  `mypy src` are clean.
- Browser e2e against the built frontend (`pytest -m e2e`): 173 passed,
  22 skipped. The lockout e2e test now logs in through a proxy header, because
  direct loopback is exempt from the lock.
- `export-openapi` is still deterministic. Only one description changed (the
  archive's `include_db`); `frontend/openapi.json` and `schema.gen.ts` are
  regenerated, and `pnpm typecheck` passes.
- Live re-run of the reviewer's PoCs on `127.0.0.1:8210`:
  - setup: built `frontend/dist`, `gen-env` secrets, the weak password
    `Sommerfest2026` (to see the startup warning), `X-Forwarded-For` for
    distinct clients as before;
  - all 37 checks pass, so every PoC for SEC-01 to SEC-07 now fails;
  - `virtubooth serve` with `*` in the proxy list exits with code 2.

### Status

| ID | Status | Commit | Change |
|---|---|---|---|
| SEC-01 | fixed | `6549ca6` | Per-IP limits key IPv6 on the /64. The global lock refuses every login, the right password included. Startup warning for weak passwords. |
| SEC-02 | fixed | `d042502` | `img.info.clear()` before both saves: no COM, EXIF, XMP or ICC in the photo or the thumbnail. |
| SEC-03 | fixed | `76356a6` | The archive's DB copy has `admin_sessions` and `export_jobs` emptied and is VACUUMed. README.txt and `include_db` list the contents. |
| SEC-04 | fixed | `bf6dfe0` | Full origin (scheme, host, port), proxy-aware; rules below. |
| SEC-05 | fixed | `22e6bee` | Allow-list of root files. HTML and its `.br`/`.gz` siblings are not served. |
| SEC-06 | fixed | `5086d41` | Logout closes the session's streams at once (bus signal). At most 4 streams per session. |
| SEC-07 | fixed | `c8dee31` | The access log parses the query and masks every key that decodes to `t`. |
| SEC-08 | INT-A | – | INT-A removes `VB_DEV=1` from the image. Re-check after the merge: `USER 10001:10001`, no `.env` in the context, `.dockerignore` an allow-list. |
| SEC-09 | fixed | `22e6bee` | HTML, the gate and redirects send `private, no-cache`; the `?t=` 303 sends `no-store`. |
| SEC-10 | partly fixed, rest accepted | `4adf95d` | At most 20 fingerprint rows per guest (banned ones are kept). Evasion and poisoning are accepted (see below). |
| SEC-11 | accepted | – | See below. |
| SEC-12 | accepted | – | See below. |
| SEC-13 | deferred (time) | – | The pins are not a day old yet; see below. |
| SEC-14 | fixed | `d042502` | At most 100 scans per JPEG. The size is checked from the header before decoding (verified, with a test). |
| SEC-15 | fixed | `fa9082a` | `*` in `VB_FORWARDED_ALLOW_IPS` / `--forwarded-allow-ips` is a config error. No compose file or `.env.example` uses `*`. |

### What the host needs to know

**Admin login (SEC-01)**
- Per-IP limits are unchanged: 5 per minute, 20 per hour.
- IPv6 clients now share one budget per /64. This applies to every per-IP
  budget (login, API, uploads and new guests per IP). On a venue Wi-Fi with
  IPv6, all guests share the venue's /64, just as IPv4 guests share the NAT
  address. The per-IP defaults already assume that.
- **Global lock:** after 20 wrong passwords within 15 minutes, from any
  address, **every** login is refused for **5 minutes**, the correct
  password too. The answer is `429 login_locked` with `Retry-After`, and the
  login page says how long to wait.
  - Each new failure after the window refills a little and trips the lock
    again. So a distributed attack gets at most about 80 guesses an hour,
    whatever its number of addresses, and a lucky guess never gets through.
  - The trade-off: during an attack the admin may not be able to log in from
    outside for minutes at a time.
- **What keeps working during a lock:**
  - admins who are already logged in (sessions last 12 h): log in before the
    party;
  - direct loopback logins: a request from the machine itself straight to the
    app's port, with no `X-Forwarded-For`/`Forwarded` header. A forwarded
    `127.0.0.1` never counts. In Docker this is only
    `docker compose exec app …`: a browser through an SSH tunnel arrives from
    the Docker gateway, not from loopback;
  - a restart (`docker compose restart app`) clears the lock, because the
    buckets live in memory.
- **Password warning:** at startup the log warns when `VB_ADMIN_PASSWORD` is
  shorter than 16 characters or has very little variety (fewer than 8
  distinct characters, or only one character class below 20 characters). The
  password itself is never logged. The 12-character minimum stays, so an
  existing deployment keeps starting.

**CSRF origin check (SEC-04)**

Origin (or Referer) must match **scheme, host and port** of one of:
1. an entry of `VB_ALLOWED_ORIGINS` (exact);
2. `VB_PUBLIC_BASE_URL` (exact; this also covers proxies that rewrite
   `Host`);
3. the request's own origin: the scheme uvicorn derived (a trusted
   `X-Forwarded-Proto` turns it into https) plus the `Host` header;
4. `https://<Host>` on a plain-http request, only behind a TLS proxy that the
   app doesn't trust for `X-Forwarded-Proto`. That is the case when the proxy
   still sends `X-Forwarded-Proto: https` (Caddy, Traefik, the nginx config
   in DEPLOY.md), when `VB_PUBLIC_BASE_URL` is https, or when
   `VB_COOKIE_SECURE=true`.

An `http://` origin is refused for any request that came in over TLS (the own
scheme or `X-Forwarded-Proto` is https), and for the host of an https
`VB_PUBLIC_BASE_URL`. Only `VB_ALLOWED_ORIGINS` can allow one.

Verified setups:

| Setup | Result |
|---|---|
| Plain http on a laptop or in the LAN | works |
| Compose with Caddy, Traefik or nginx, proxy trusted | works |
| The same proxy not trusted (still sends `X-Forwarded-Proto`) | works |
| Proxy without `X-Forwarded-Proto`, but an https public URL or `VB_COOKIE_SECURE=true` | works |
| Coolify | works |
| A proxy that rewrites `Host` | works through the public URL |
| The host on the server via an SSH tunnel (`http://localhost:8000`) while the public URL is https | works |

The only newly refused case is a misconfiguration: a proxy that sends no
`X-Forwarded-Proto`, while the public URL is left at `http://localhost:8000`
and `VB_COOKIE_SECURE` is not `true`. The fix is to set `VB_PUBLIC_BASE_URL`
to the real https URL, which the QR codes need anyway.

**Live screens (SEC-06)**
- Logging out ends that session's open event streams within milliseconds.
  The other tabs then reconnect, get 401 and go to the login page.
- One login (one browser) keeps at most 4 live streams. A fifth tab closes
  the oldest stream, which reconnects and replays what it missed.
- Expiry and a password change are still caught by the periodic check (at
  most about 45 s).

**Archive (SEC-03)**

`virtubooth.db` in the admin's archive and in `python -m
virtubooth.tools.export` contains:
- guests: pseudonyms, Instagram handles, IPs, user agents, fingerprints,
  bans;
- all photo rows, hidden and deleted ones included;
- device bans;
- the audit log, including the addresses admins logged in from;
- the upload settings.

It no longer contains admin sessions or export jobs. Both tables are emptied,
not dropped, so the copy can still be restored as a backup (every admin then
logs in again). The file is VACUUMed, so nothing deleted earlier can be
recovered from it.

**Other changes**
- Root files (SEC-05): only `boot-check.js`, `gate-hint.js`, `icon.svg`,
  `favicon.ico`, `apple-touch-icon.png` and `robots.txt` are served from the
  build root. A new file in `frontend/public/` needs an entry in
  `PUBLIC_ROOT_FILES`. Amendment in `contracts/web-serving.md` §7.
- Uploads (SEC-02, SEC-14):
  - nothing the phone or client wrote survives: comments, EXIF/GPS, XMP, ICC
    and trailing bytes are all dropped;
  - a JPEG with more than 100 scans is refused as `invalid_image`. Browsers
    write 1 scan, progressive encoders about 10.
- Fingerprints (SEC-10): a guest keeps the newest 20 fingerprint rows. Rows
  whose hash is banned are always kept.
- `VB_FORWARDED_ALLOW_IPS='*'` (SEC-15): the server refuses to start and
  names the alternative: the proxy's IP or subnet.

### Accepted, with reasons

- **SEC-10 (evasion, ban poisoning).** The fingerprint is a hint by design
  (BRIEF: "the fingerprint used only as a hint").
  - A guest who changes it evades a device ban the same way as one who clears
    cookies.
  - Poisoning needs a guest who is about to be banned to predict another
    device model's exact hash.
  - The data to warn about shared fingerprints is there (`shared_with` on
    every fingerprint of `GET /api/admin/users/{user_id}`). Showing it in the ban
    sheet before a device ban is a UI follow-up for the admin app (frontend,
    not part of this change).
  - The row growth, the cheap part, is fixed.
- **SEC-11 (`uid_token` has no expiry).** Accepted.
  - The token is an HMAC over the public id, keyed with `VB_SECRET_KEY`, so
    it can't be forged or enumerated (a forged one gets `needs_consent`).
  - It only identifies a guest *device* inside a party that already needs the
    party token, and it grants nothing beyond that guest's own photos.
  - A party lasts one night. Adding an expiry would log guests out of their
    identity mid-party when their localStorage outlives the cookie.
  - **Reset:** rotating `VB_SECRET_KEY` invalidates every uid token at once.
    It also invalidates every access cookie and every admin session, so every
    guest joins again and gets a new pseudonym.
- **SEC-12 (exports filling the disk).** Accepted. Both bounds exist
  (verified):
  - `ExportService._prune` (`services/exports.py`) keeps only the newest 10
    finished export files and deletes older ones with their records;
  - `check_free_space` (`tools/_common.py`) runs before every archive, both
    the admin job (`export_runners.run_archive`) and the CLI
    (`tools/export.py`). It refuses unless the photos' size plus 5 % plus
    10 MB is free.

  The timelapse is not checked, but an H.264 file is a small fraction of the
  photos it is made from. Only an admin can start exports (one job at a
  time), and the admin can delete them.
- **SEC-14 (no timeout on decoding).** The decode work is bounded instead:
  - the size comes from the header and is checked before `load()` (exactly
    1080×1440 for both built-in activities, `max_side` otherwise);
  - `MAX_IMAGE_PIXELS` is 25 M;
  - at most 100 scans;
  - 8 MB per upload, 10 uploads per guest per minute, and the thread pool.

  A timeout on a C decoder can't stop the work anyway; it only frees the
  request.

### Deferred

- **SEC-13 (`minimumReleaseAgeExclude`).** Checked on 2026-10-13 at
  07:17 UTC with `npm view <pkg> time --json`:

  | Package | Published (UTC) |
  |---|---|
  | `vitest@5.0.4` | 2026-10-12 09:47 |
  | `@vitest/mocker@5.0.4` | 2026-10-12 09:46 |
  | `@vitest/spy@5.0.4` | 2026-10-12 09:46 |
  | `zod@4.6.7` | 2026-10-12 16:29 |

  None is a day old yet. Without the four entries,
  `pnpm install --frozen-lockfile` fails now ("within the minimumReleaseAge
  cutoff"; tried and reverted). **To do after 2026-10-13 16:30 UTC:** delete
  the whole `minimumReleaseAgeExclude` block and its comment from
  `frontend/pnpm-workspace.yaml`, then run
  `pnpm install --frozen-lockfile`. The three vitest entries could already
  go after 09:47 UTC.

### Doc lines for INT-A's files (for the orchestrator to apply)

**`README.md`**
- Line 58 (upload pipeline): "re-encoded (EXIF and GPS stripped)" → "re-encoded
  (all metadata stripped: EXIF/GPS, XMP, ICC, comments)".
- Line 119, `VB_ADMIN_PASSWORD` row: "Admin password (min. 12 chars; use 16+
  random ones, the log warns otherwise; `gen-env` makes one). Changing it ends
  all admin sessions."
- Line 128, `VB_ALLOWED_ORIGINS` row: "Extra origins for the CSRF check,
  compared exactly (scheme, host, port), e.g. `https://party.example.com`.
  Rarely needed: `VB_PUBLIC_BASE_URL` is accepted anyway. The only way to
  allow an `http://` origin on an https deployment."
- Line 140, `VB_FORWARDED_ALLOW_IPS` row: append "`*` is refused at startup."
- Lines 195-197 (proxy notes): "The CSRF check compares the full origin,
  scheme included. Behind TLS it accepts `https://<host>`: the public URL,
  the request's own origin, or `https://<Host>` when the proxy says
  `X-Forwarded-Proto: https`. `http://` origins are refused on https
  deployments. If the proxy rewrites `Host`, set `VB_PUBLIC_BASE_URL` (or
  `VB_ALLOWED_ORIGINS`)."
- Lines 285-289 (admin login), replace with: "Sessions last
  `VB_ADMIN_SESSION_HOURS` (12 h); log in before the guests arrive. Login is
  rate limited per IP (5 per minute, 20 per hour; IPv6 per /64). After 20
  wrong passwords within 15 minutes from anywhere, **every** login is refused
  for 5 minutes ("Zu viele Fehlversuche"), the correct password too, so
  spreading guesses over many addresses gains nothing. Admins who are logged
  in keep working. To get in during a lock: wait, or restart the container
  (`docker compose restart app`; the counters live in memory). A login sent
  from the server itself straight to the app's port (no proxy) is exempt.
  Keep the password long and random (`gen-env` does); the log warns at
  startup when it is shorter than 16 characters or very repetitive."
- Line 345 (CLI export): "a consistent copy of `virtubooth.db` (guests with
  IPs, fingerprints and bans, all photo rows, the audit log; without admin
  sessions and export jobs, vacuumed so nothing deleted earlier can be
  recovered; leave it out with `--no-db`)".
- Line 386 (data minimisation): "Photos are re-encoded, so EXIF/GPS, XMP, ICC
  and comment data from the phone never reaches the disk."
- Line 445 (troubleshooting), new text: "| Admin login says "Zu viele
  Fehlversuche" | 20+ wrong passwords within 15 minutes from anywhere: every
  login waits 5 minutes, the correct one too. Logged-in admins keep working.
  Wait, or restart the container to clear it. |"
- New troubleshooting row: "| `403 bad_origin` behind https only | The CSRF
  check compares the scheme. Set `VB_PUBLIC_BASE_URL=https://<host>` and
  trust the proxy (`VB_FORWARDED_ALLOW_IPS`). |"
- Admin section: "Logging out ends the live screens of that login at once. One
  browser keeps at most 4 live tabs; a fifth reconnects the oldest."

**`.env.example`**
- `VB_ADMIN_PASSWORD` comment: "Password for /admin. At least 12 characters;
  use 16+ random ones (the log warns otherwise; gen-env makes one). Changing
  it ends every admin session."
- `VB_FORWARDED_ALLOW_IPS` comment, last sentence: "... and never use "*"
  (refused at startup): anyone reaching the port could then pick their own IP
  for rate limits."
- `VB_ALLOWED_ORIGINS` comment: "Extra origins accepted by the CSRF check
  (comma-separated, compared exactly: scheme, host and port), e.g.
  https://party.example.com. VB_PUBLIC_BASE_URL is always accepted, so this
  is only needed for additional hostnames."

**`docs/DEPLOY.md`**
- §5 point 2: "Pass the original `Host` header. The CSRF check compares the
  browser's `Origin` (scheme, host, port) with `VB_PUBLIC_BASE_URL` and with
  the request's own origin; set `VB_PUBLIC_BASE_URL=https://<your-domain>`
  in any case."
- §5 point 3: append "`*` is refused."
- §5.4 Coolify (SEC-15): "The compose file trusts all private ranges by
  default. To narrow it, set `VB_FORWARDED_ALLOW_IPS` to Coolify's proxy
  network:
  `docker network inspect coolify --format '{{(index .IPAM.Config 0).Subnet}}'`.
  Other containers on Coolify's shared network could otherwise send forged
  `X-Forwarded-For` straight to `app:8000`. The global login lock still caps
  them."
- New short section "Locked out of the admin login": the 20-per-15-minutes /
  5-minute rule, "logged-in sessions keep working", and
  `docker compose restart app` clears it.

**`docs/ARCHITECTURE.md`** (lines 42-44, CSRF)

"every POST/PUT/PATCH/DELETE must carry an `Origin` (or `Referer`) whose full
origin (scheme, host, port) is `VB_PUBLIC_BASE_URL`'s, an entry of
`VB_ALLOWED_ORIGINS`, or the request's own (scheme + `Host`; also
`https://<Host>` behind an untrusted TLS proxy). `http://` origins are refused
on https deployments."

**Compose files:** no change is needed for SEC-15 (neither uses `*`).
Optionally, `docker-compose.coolify.yaml` could gain this comment at
`VB_FORWARDED_ALLOW_IPS`: "narrow to the coolify network's subnet if other
apps share it".

**`docs/overhaul/contracts/api.md`** (not INT-A's, not changed here)
- §3, `login_locked` row: "every login for 5 min after 20 wrong passwords in
  15 min from anywhere, the right password included".
- §4: "The stream ends at once on logout. Otherwise (expiry, password change)
  the session is checked at most every 30 s. A session holds at most 4
  streams; a fifth closes its oldest, which reconnects and replays."
- §6.2 `archive`, `include_db`: "without admin sessions and export jobs,
  vacuumed".
