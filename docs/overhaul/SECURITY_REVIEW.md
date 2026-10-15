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
| SEC-13 | fixed | 2026-10-13 18:53 UTC | The exclusions are removed once the pins were a day old; see below. |
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

- **SEC-13 (`minimumReleaseAgeExclude`), done on 2026-10-13 at 18:53 UTC:** the block is
  removed and `pnpm install --frozen-lockfile` passes (lockfile unchanged, supply-chain
  policies pass). The original note: checked on 2026-10-13 at
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

## Review 2: QR codes, settings, Live Wall (2026-10-14)

Reviewer: security agent, branch `sec/review` (from `main` at `3b1daab`).

**Scope.** The delta `0ff9bd4..main`:
- admin password change (scrypt, `admin.password`, `POST /api/admin/settings/password`,
  `virtubooth reset-admin-password`);
- QR codes (`party_codes`, `party_code_tokens`, the new access cookie, the wrong-token
  limiter);
- the Live Wall (`/livewall`, its password and cookie, screen API, media, SSE, the admin
  API under `/api/x/wall/admin/`);
- the poster template upload;
- the heartbeat `/api/here`;
- the analysis worker and the guest opt-out;
- CSP and static serving for `wall.html` and the pdf.js worker.

**Method.** The same as review 1:
1. The code was read end to end.
2. Each suspicion was checked against a throwaway server on `127.0.0.1:8417`, with the
   built `frontend/dist`, its own data dir and `VB_WALL_WORKER=off`.
3. `X-Forwarded-For` stood in for distinct client addresses.

The ML extra was not installed, so the analyzers themselves were only read, not run.

### Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | |
| High | 0 | |
| Medium | 1 | WALL-01 (fixed) |
| Low | 6 | ARCH-01, QR-01, WALL-02, WALL-03, HERE-01, ANA-01 (all fixed) |
| Info | 7 | R2-I1 … R2-I7 |

The new auth paths hold:
- **Wall cookie.** It reaches only `/livewall`. It cannot read guest or admin data,
  and guest cookies cannot read the wall.
- **Hidden photos.** They leave the wall feed and all three media sizes at once,
  the cached 1280 px copy included.
- **Password change.** It needs the current password and ends every other session.
- **QR tokens.** They are looked up by hash and never reused. The audit log keeps only
  their last 4 characters.
- **Poster template.** It is admin-only and served sandboxed as an attachment.

The one Medium was the wall login. It was rate limited per address only, and the wall
password (6 characters minimum) opens every photo on the wall, which is more than a guest
can see.

### Findings

#### WALL-01 · Medium · confirmed · fixed: the wall login has no global lock

**Affected code:** `backend/src/virtubooth/extensions/wall/auth.py` (`login`, `LoginLimits`)

**Description.** `POST /livewall/api/session` checks 5/min and 20/h per address (IPv6:
per /64) and then always runs scrypt. The admin login (SEC-01) has a global failure
lock; the wall login had none. So guesses spread over many addresses are only bounded by
scrypt (2 parallel slots, about 12 guesses/s on the test machine, ~40,000 per hour). The
password minimum is 6 characters.

**What the wall password opens:**
- every visible photo of every guest (guests only see their own);
- authors' pseudonyms (and Instagram handles when shown);
- with the QR overlay on, the active party token.

**Repro** (`t1_wall_brute.py`, wall password `party1`):
```python
for i in range(200):                       # 200 addresses x 5 guesses
    ip = f"198.51.{i//250}.{i%250+1}"
    for j in range(5):
        c.post("/livewall/api/session", json={"password": f"wrong{i}-{j}"},
               headers={"X-Forwarded-For": ip})
# -> {403: 1000}                            1000 checked guesses in 84 s, no lock
c.post("/livewall/api/session", json={"password": "party1"},
       headers={"X-Forwarded-For": "203.0.113.9"})
# -> 200, vb_wall cookie; /livewall/api/feed -> 200 with every photo
```

**Fix (`5e541e0`).** The same model as SEC-01. After 20 wrong wall passwords within
15 minutes, from any address, every wall login is refused for 5 minutes, the right
password included: `429 login_locked` with `Retry-After` and `no-store`.
- The lock is checked before the per-IP buckets and before scrypt.
- Walls that are logged in keep their cookie, and admin sessions still pass.
- A restart clears the lock (the buckets live in memory).
- The wall login screen already shows the server's message ("Zu viele Fehlversuche. Die
  Anmeldung ist kurz gesperrt.").

Re-run of the PoC: 19 × `403`, then `429 login_locked`; the right password from a fresh
address gets `429` with `Retry-After: 300`.

Test: `tests/api/test_wall_auth.py::test_global_lockout`. FEATURES.md and ARCHITECTURE.md
describe the lock.

#### ARCH-01 · Low · confirmed · fixed: the archive's database copy holds the password hashes

**Affected code:** `backend/src/virtubooth/tools/export.py` (`scrub_snapshot`)

**Description.** Passwords can now be set in the admin, so `settings` holds the scrypt
hashes `admin.password` and `x.wall.password`. The archive's DB copy (`include_db`)
carried both. That lets anyone with the zip crack them offline. Before this change the
admin password was only in the environment.

**Repro.** `take_snapshot(data, tmp)` on the test data dir, then
`SELECT key FROM settings` → `admin.password`, `x.wall.password` with `scrypt$15$8$1$…`.

**Fix (`5aec2f2`).** The scrub also deletes `admin.password` and every
`x.<id>.password` row before the VACUUM. A restored copy falls back to
`VB_ADMIN_PASSWORD` and to a wall without a password. README.txt in the archive says so,
and also that the QR codes with their tokens are in the copy (see the accepted risks).

Test: `tests/api/test_security_fixes.py::test_snapshot_drops_password_hashes`.

#### QR-01 · Low · confirmed · fixed: wrong tokens from one device lock new guests out of a shared network

**Affected code:** `backend/src/virtubooth/middleware.py` (`_token_entry`),
`core/ratelimit.py` (`TOKEN_FAILURES_PER_MIN`)

**Description.** While an address's wrong-token bucket (60/min) is empty, every `?t=`
gets the gate unchecked, valid tokens included. At a party, all guests on the venue
Wi-Fi share one IPv4 (or one /64). One device sending a wrong token every second keeps
every new guest on that network out. Guests on mobile data and guests who joined already
are not affected.

**Repro** (`t3_token.py`): 61 wrong tokens from `192.0.2.77`, then the valid token from
the same address → `404`, `X-VB-Page: gate`. From `192.0.2.78` → `303`.

**Recommendation.** Always check a token that is well-formed. The guessing oracle the
limiter hides is worthless against 144-bit generated tokens and 16+ character custom
tokens. Keep counting failures, and log or alert on bursts. If an oracle limit is still
wanted, key it on address plus `vb_vid`, so one device cannot empty its neighbours'
budget.

**Fix (`00b78a5`, branch `polish/backend`).** A well-formed token (`TOKEN_RE`,
16–128 characters of `[A-Za-z0-9_-]`) is always looked up; a malformed one never is.
The per-address counter (`token_fail_ip`, 60/min) stays, but only for wrong tokens:
over it, their gate answer is held back 1 s (`TOKEN_FAIL_DELAY`, an `asyncio.sleep`,
no thread) and the burst is logged once a minute per address. The right token from a
throttled address gets `303` at once. Tests: `tests/api/test_code_access.py`
(`test_wrong_tokens_never_block_valid_ones`, `test_malformed_tokens_are_not_looked_up`,
the IPv6 /64 case).

#### WALL-02 · Low · confirmed (code) · fixed: the wall's 1280 px copy of a deleted photo can survive on disk

**Affected code:** `extensions/wall/hub.py` (`_handle` → `drop_cached`), `extensions/wall/media.py`

**Description.** The cached copy `<data>/wall/cache/m/<id>.jpg` is removed only when the
wall's translator handles `photo.deleted` from the in-memory bus. It is missed when:
- the wall extension is not loaded when the photo is deleted;
- the translator falls behind and resyncs past the event;
- the app stops right after the delete.

The file is never served again, because `/livewall/media` checks visibility. But it stays
in the data volume (and its backups), against the promise that deleted photos are gone
for good.

**Recommendation.** Two options:
- In `WallHub.start()` and after a translator resync, sweep the cache. Delete every file
  whose photo is deleted or unknown. It is a single query and a directory listing.
- Or let `ModerationService.delete_photo` unlink the copy in its on-commit hook.

**Fix (`6528aec`, branch `polish/backend`).** Both:
- A new generic hook `Extension.derived_files(core, public_id)`: files an extension
  made from a photo. `delete_photo` unlinks them with the photo's own files on commit,
  with no event involved. The wall registers its cached copy.
- `media.sweep_cache` runs at the wall's start, after its translator missed events and
  every hour. It removes copies whose photo is deleted, hidden or unknown, and temp
  files older than 10 minutes.

Tests: `tests/api/test_wall_feed.py` (`test_deleting_removes_the_copy_without_the_event`,
`test_the_sweep_removes_copies_of_deleted_hidden_and_unknown_photos`).

#### WALL-03 · Low · fixed: no cap on wall event streams

**Affected code:** `extensions/wall/screen_api.py` (`stream`)

**Description.** The admin stream holds at most 4 streams per session (SEC-06).
`/livewall/api/stream` has no limit per wall cookie or admin session. Whoever has the
wall password (or a stolen wall cookie) can open streams until file descriptors or memory
run out. Each stream also re-checks its cookie every 30 s.

**Recommendation.** At most 4 open streams per wall cookie value (or per address), and
close the oldest one, like SEC-06.

**Fix (`5cfbc1d`, branch `polish/backend`).** The wall bus keys each stream by a hash of
its wall cookie (or the admin session) and keeps at most 4 (`EventBus.per_session`); a
fifth closes the oldest. New wall cookies carry a random nonce
(`<gen>.<issued>.<nonce>`), so screens that log in within the same second get their own
cap; cookies without it stay valid. Later (`e35afa7`) the screen's GET routes also got
rate limits per wall cookie, else per address: 120/min for session, feed, categories
and stream, 1200/min for media. Test:
`tests/api/test_wall_stream.py::test_one_wall_cookie_keeps_at_most_four_streams`.

#### HERE-01 · Low · fixed: the heartbeat writes on every request

**Affected code:** `services/presence.py` (`here`), `repositories/presence.py` (`beat`)

**Description.** Every `POST /api/here` of a joined guest is one write transaction, with
no server-side interval. It is bounded only by the per-guest API budget. One guest
reached 301 × `200` in 0.37 s, then `429`. One address can create 120 identities per
10 minutes, each with its own budget, and so several hundred write transactions a second.
Other guest writes (`PATCH /api/me`) behave the same way, so this adds no new class. The
online time cannot be inflated: a beat adds only the real time since the last one, at most
150 s.

**Recommendation.** Skip the write for a visible beat less than ~20 s after the guest's
previous one. A per-guest timestamp in memory is enough, as in `note()`. The accounting
does not change, because the next beat adds the elapsed time.

**Fix (`7a09832`, branch `polish/backend`).** As recommended: a visible beat less than
20 s (`BEAT_MIN_SECONDS`) after the guest's last written visible beat is not written.
The timestamp lives in memory, on the beats' own clock. Hidden beats are always written
(they close the visit), and the next visible beat after one opens a new visit at once.
Test: `tests/api/test_here.py::test_quick_visible_beats_are_not_written`.

#### ANA-01 · Low · fixed: toggling the analysis opt-out requeues all of the guest's photos every time

**Affected code:** `repositories/users.py` (`set_analysis_opt_out`), `PUT /api/me/analysis`

**Description.** Each change deletes the guest's facts and resets every analysis row to
`pending`. A guest flipping the switch (bounded only by the 300/min budget) keeps the
worker re-analysing their photos. Newer photos still go first, so this wastes CPU at
nice 10 rather than blocking anyone. The opt-out itself is correct:
- `claim` reads it;
- `finish` refuses rows that left `running`, so a flip during an analysis cannot store ML
  facts;
- categories that need ML exclude opted-out guests.

**Recommendation.** A small per-guest limit on this route (e.g. 5 per minute).

**Fix (`54a405f`, branch `polish/backend`).** No refused requests: the switch always
applies. Only a real change does anything, and a guest's photos are queued again at
most once per 5 minutes (`ANALYSIS_REQUEUE_SECONDS`, in memory). Inside that window:
- switching off still drops facts and boxes at once, and a running analysis goes back
  to `pending` (`finish` refuses its ML result);
- switching on touches nothing.

The worker's new sweep (`Worker.sweep`, `jobs.stale`) redoes analyses whose stored
analyzer versions no longer match the guest's current choice. It runs at start, when the
active analyzers change, and every 5 minutes. So switching back and forth costs at most
about one pass per 5 minutes. Tests: `tests/api/test_wall_integration.py::
test_switching_the_opt_out_back_and_forth_requeues_once` and the sweep tests in
`tests/unit/test_enrich_pipeline.py`.

#### Info

- **R2-I1 · revoked codes keep joined guests in.**
  - By design (`has_access`): a revoked or re-tokened code shuts out only browsers that
    never joined.
  - To lock everyone out (a leaked code, the end of the party), rotate `VB_SECRET_KEY`.
    That ends every cookie and every admin session.
  - Worth a line in the admin's revoke dialog.
- **R2-I2 · the QR overlay shows an active token to the wall.**
  - With `overlay.qr` on, `/livewall/api/feed` and the `config` event carry an entry URL
    with a live token, by design (the TV shows it).
  - So the wall password also yields guest access.
- **R2-I3 · the analysis worker's resources.**
  - Bounds: nice 10, thread limits, a recycle at 200 photos or 900 MB RSS (checked after
    each photo), and it parses only the stored, re-encoded JPEGs.
  - No hard limit: in the default 1 GB container the OOM killer may pick uvicorn instead
    of the worker. Writing `1000` to `/proc/self/oom_score_adj` in `tune_process()` would
    make the kernel kill the worker, which the supervisor restarts.
  - The worker inherits the whole environment (`VB_SECRET_KEY`, `VB_ADMIN_PASSWORD`). It
    needs none of it, but it has DB write access anyway, so dropping them is
    defence in depth only.
- **R2-I4 · model downloads.**
  - The safeguards: HTTPS, commit-pinned URLs, SHA256 checked while streaming, an atomic
    rename, and downloads only by CLI or Docker build, never by the app.
  - The stream has no byte cap (a hostile mirror could fill the disk before the hash
    fails), and urllib follows redirects, also to http.
  - Fix: stop reading after `model.size` bytes.
- **R2-I5 · wall media cache.**
  - Wall media are sent with `private, max-age=86400`. After a hide, the TV's browser
    cache keeps the file for a day. The wall drops it from the playlist at once
    (`photo.remove`).
- **R2-I6 · small disclosures.**
  - `GET /livewall/api/session` tells anyone whether a wall password is set (409 versus
    401).
  - Each valid `?t=` scan writes `visitors` and `code_visitors` outside the API budget
    (needs a valid token).
- **R2-I7 · weak custom tokens.**
  - The custom token rule (16–128 characters from `[A-Za-z0-9_-]`, at least 6 distinct)
    still allows guessable phrases such as `Geburtstag-Lena-30`.
  - Generated tokens have 144 bits.
  - The admin UI could warn on dictionary-like custom tokens.

### Verified OK (coverage)

**Admin password**
- **Hashing** (`core/passwords.py`):
  - scrypt with log2 N = 15, r = 8, p = 1, a 16-byte random salt and a 32-byte key;
  - `verify` bounds the parameters read from the stored string (log2 N ≤ 20, r ≤ 32,
    p ≤ 16) and decodes base64 strictly;
  - `compare_digest`; at most 2 scrypt runs at once.
- **Change endpoint:**
  - router-level `require_admin` plus the current password;
  - a wrong current password answers 403 and counts towards the global lock, with the
    login's per-IP limits;
  - length 12–256;
  - the caller's session is re-tagged; every other session is deleted and its streams
    closed on commit.
- **Which password applies** (live): after a change, the old `VB_ADMIN_PASSWORD` gets
  401 and the new one 200. Sessions carry an HMAC tag of the stored hash (or of the env
  password), read on every request, so a CLI reset applies at once.
- **CLI:**
  - `reset-admin-password --from-env` deletes the hash; a new password must be 12–256
    characters;
  - every session ends; the reset is audited;
  - startup warnings about weak passwords apply only to the env password.

**QR codes**
- **Lookup:** by SHA-256 in `party_code_tokens`, active codes and the current token
  only. Every token a code ever had stays, so reuse answers `409 token_taken`
  (verified live).
- **Access cookie:**
  - `sign("access", "<id>.<gen>")`, parsed with a strict regex (`[1-9]…\.[1-9]…`);
  - a forged or tampered value is None;
  - legacy MAC cookies count as code 1, generation 1. They are "current" only while
    code 1 still has its first token, else "stale", which lets only joined guests in.
- **Token exposure:**
  - the audit log keeps `token_end` (4 characters); the full token was not in
    `/api/admin/audit` (verified);
  - full tokens appear only in `/api/admin/codes*` and the admin event stream (needed for
    printing).
- **Rules:**
  - all code routes are behind `require_admin`;
  - the target must be a loaded extension;
  - notes may not contain control characters;
  - incoming `?t=` longer than 128 characters is not hashed.

**Live Wall**
- **Cookie** (live): `HttpOnly; Max-Age=2592000; Path=/livewall; SameSite=strict`
  (`Secure` behind https).
  - The value is `sign("wall", "<gen>.<issued>")`; the generation grows on every password
    change, removal and "Alle Wände abmelden".
  - Its purpose differs from the access and visitor cookies, so the values cannot be
    swapped.
- **Separation** (live):
  - wall cookie only: `/api/me/photos` → 404 gate, `/api/x/wall/admin/config` → 401;
  - guest cookies: `/livewall/api/feed` → 401;
  - CSRF: `POST /livewall/api/session` without `Origin` → 403;
  - admin bypass only through a valid admin session (`SameSite=Strict`).
- **Hidden and deleted photos** (live):
  - after a hide, the feed is empty and `s`, `m` and `l` of the photo answer 404,
    although the 1280 px copy is still cached;
  - visibility is checked from the DB on every media request;
  - a ban hides the guest's photos; deletion drops the copy (but see WALL-02).
- **API budget:** the admin exemption on `/api/x/<id>/admin/` needs a valid admin
  session. Anonymous and guest calls there still count against their budget and get 401.
- **SQL:** the category SQL is built only from the static catalogue; values are bound.

**Poster template**
- **Upload checks:** `Content-Length` required, at most 8 MB, chunked bodies refused,
  `%PDF-` within the first 1024 bytes.
- **Storage:** a fixed path `<data>/poster/template.pdf`, written atomically.
- **Serving:** only `GET /api/admin/poster/template`, as an attachment with
  `CSP: sandbox`, `no-store` and `nosniff`.
- **Auth before the body:** an anonymous 1 MB `PUT` gets 401 before the body is read
  (live). The middleware's streamed-body exemption covers only this one path.

**Heartbeat:** `AccessDep`, the per-guest budget (verified), and the online-time
accounting described in HERE-01.

**Analysis**
- **Process:** a separate subprocess that exits on stdin EOF, runs at nice 10 with
  limited threads, and is recycled.
- **Input:** it reads stored photos only. Those were re-encoded at upload with their size
  checked from the header. It decodes in draft mode to ≤ 1280 px, and the ML libraries
  get numpy arrays, never files.
- **What it stores:** numeric facts, boxes (rectangles and German labels) and detail
  lines. Scratch data (face crops, landmarks, blendshapes, CLIP vectors) stays in memory
  for one photo (`pipeline.merge`, `Outcome.data`).
- **Admin-only output:** per-photo analysis and boxes. The wall gets only `people`,
  `faces`, `hands` and `smiles`.

**CSP and static serving**
- **CSP:** unchanged: `default-src 'self'`, no `unsafe-eval`, no `blob:` workers.
- **pdf.js:**
  - version 6.4.299 (after the CVE-2024-4367 fix), with `useWasm: false`;
  - its worker is a hashed `/assets/*.mjs`, served as `text/javascript`.
- **wall.html:** served only via `/livewall`; `/wall.html` and its `.br`/`.gz` siblings
  are 404.
- **Frontend:** the new code has no HTML sinks (`innerHTML`,
  `dangerouslySetInnerHTML`, `eval`).

### Status

| ID | Severity | Status | Commit |
|---|---|---|---|
| WALL-01 | Medium | fixed | `5e541e0` |
| ARCH-01 | Low | fixed | `5aec2f2` |
| QR-01 | Low | fixed | `00b78a5` |
| WALL-02 | Low | fixed | `6528aec` |
| WALL-03 | Low | fixed | `5cfbc1d` (+ screen rate limits `e35afa7`) |
| HERE-01 | Low | fixed | `7a09832` |
| ANA-01 | Low | fixed | `54a405f` |
| R2-I1 … R2-I7 | Info | accepted / notes | – |

**Tests run.** Targeted backend tests: `uv run pytest -n 4` → 332 passed. The files:
- the API tests `test_admin_password`, `test_code_access`, `test_codes`,
  `test_code_guests`, `test_wall_auth`, `test_wall_feed`, `test_wall_admin`,
  `test_wall_stream`, `test_wall_integration`, `test_wall_hooks`, `test_here`,
  `test_admin_poster`, `test_enrich_analysis_api`, `test_admin_exports` and
  `test_security_fixes`;
- the unit tests `test_passwords`, `test_wall_passwords`, `test_enrich_jobs` and
  `test_enrich_models`.

`ruff check`, `ruff format --check` and `mypy` pass on the changed files. No OpenAPI or
frontend change, so no Vitest or e2e run was needed.

### Accepted risks

- **Joined guests survive revoke and re-token (R2-I1).** That is the product decision
  ("joined guests keep their session"). The escape hatch is a `VB_SECRET_KEY` rotation.
- **The archive's DB copy keeps the QR codes' current tokens.** The copy is documented as
  restorable, and blanking the tokens would break reprinting after a restore. The archive
  already holds guest IPs and fingerprints and is for the host only. README.txt now names
  the tokens. Revoke or re-token the codes after the party before passing an archive on.
- **The wall password minimum stays at 6 characters.** It is typed on a TV remote. With
  WALL-01 fixed, a distributed attack gets at most about 80 guesses an hour.
- **The wall lock can be triggered from outside.** The trade-off is the same as for the
  admin login: walls that are logged in keep running for 30 days, and admins still see
  the wall.

## Review 3: PSA (2026-10-15)

Reviewer: security agent, branch `night/sec-psa` (from `main` at `cee7da5`).

**Scope.** An attacker-centred pass over the whole app as it is on `main`. It does not
repeat the checks of reviews 1 and 2. The question was: who can get at what?
- **Targets:** guests' photos, QR tokens, secrets (admin and wall passwords, their hashes,
  `VB_SECRET_KEY`, the coming Anthropic API key), and admin or wall sessions.
- **Attacker positions:**
  - an anonymous internet user;
  - a guest with a valid cookie;
  - someone on the party Wi-Fi;
  - a viewer of the TV wall;
  - someone holding an exported archive;
  - a reader of the public repository: the tree, the full history of all refs, the images
    and CI.

**Method.**
1. The code was read with these positions in mind.
2. Every suspicion was checked live against a throwaway server on `127.0.0.1:8437`, with
   its own data dir, `gen-env` secrets, the built `frontend/dist` and
   `VB_WALL_WORKER=off`. `X-Forwarded-For` stood in for distinct clients, and
   `X-Forwarded-Proto: https` for a TLS proxy.
3. An authorization matrix was run over all 80 routes of the OpenAPI schema, each as
   anonymous, guest and wall-cookie caller.
4. A sub-agent read the git history: every patch on all 40 refs, all 1,048 paths ever
   committed and all 153 image blobs.

### Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | |
| High | 0 | |
| Medium | 1 | REPO-01 (needs a history rewrite by the owner) |
| Low | 5 | REPO-02 (fixed in the tree), COOKIE-01 (fixed), ENV-01 (fixed), ARCH-02 (fixed, preparation), EXP-01 (accepted, follow-up) |
| Info | 6 | R3-I1 … R3-I6 |

The app's access model holds from every position:
- no route answers more than its dependency allows;
- no photo leaves the wall or `/media` outside the documented rules;
- no secret appears in any API answer, event, log line or error message that was tested.

The one Medium finding is not in the code. It is in the public git history.

### Attack vectors

| Position | Vector | Result |
|---|---|---|
| Anonymous | All 80 API routes without cookies (matrix) | Holds. Every `/api/admin/*` and `/api/x/wall/admin/*` route answers 401. Guest routes answer 404 `scan_qr`. Wall routes answer 401. `/media` answers 404. |
| Anonymous | `/openapi.json`, `/docs`, `/redoc`, `/__ui`, `/ui.html`, `/.vite/manifest.json`, `*.html.gz`, `/wall.html` | All 404. Only `/livewall` (the page) is public. |
| Anonymous | Enumerating activities or pages | Holds. `/x/beer/` and `/x/nope/` give the same gate. |
| Anonymous | CORS | Holds. No `Access-Control-*` header anywhere, and `CORP: same-origin`. |
| Anonymous | Test or dev endpoints | None in `src/`. `VB_DEV` only selects placeholder pages. The e2e hooks live in `tests/`, which is not in the image. |
| Anonymous | Brute-forcing tokens, admin or wall passwords | Covered by reviews 1 and 2 (QR-01, SEC-01, WALL-01). Not repeated. |
| Anonymous (DNS rebinding) | A page that rebinds its own name to the server's address | The CSRF check accepts it, because `Origin` and `Host` agree. There are no cookies to ride on, so all it gets is login attempts, still limited per IP. See R3-I1. |
| Guest | Another guest's photos (`/media`, `/api/me/photos`, query and path IDs) | Holds. Photo and user ids are 96-bit random. No guest answer carries another guest's ids. |
| Guest | A forged or another guest's `vb_uid` | Holds. The value is an HMAC. A forged one gets `needs_consent`. |
| Guest | A **planted** `vb_uid` (attacker's own signed id in the victim's browser) | **COOKIE-01**: the victim silently became the attacker. Fixed on https. |
| Guest | The wall API with guest cookies; guest API with the wall cookie | Holds (401 and 404). |
| Party Wi-Fi | An http deployment | Everything travels in clear: the token in the QR URL, the cookies, the passwords. Phones only open the camera over https anyway. Accepted (R3-I2). |
| Party Wi-Fi | An https deployment: cookie injection via plain http | COOKIE-01 (fixed). The other cookies are worthless when planted (see COOKIE-01). |
| Party Wi-Fi | Token in Referer | Holds. `Referrer-Policy: no-referrer` everywhere, and the `?t=` entry redirects (303, `no-store`) to a URL without the token. |
| TV wall viewer | What the screen and its API show | Visible photos only. Pseudonyms are shown. Instagram handles appear only with `show_instagram`. The QR overlay shows a live token (R2-I2, by design). |
| TV wall viewer | Photos inside the delay; hidden photos | Holds. Inside `delay_s`: `/livewall/media` gives 404 and the feed leaves the photo out. Hidden photos give 404 in all three sizes. |
| TV wall viewer | The TV browser's cookies | `vb_wall` is HttpOnly with `Path=/livewall`. An **admin session** opened on the TV would give the whole admin (R3-I4). |
| Archive holder | `virtubooth.db`, CSVs, README | No admin sessions and no password hashes (reviews 1 and 2). The QR tokens are there (accepted in review 2). Now also no `*.secret` setting (ARCH-02). Two smaller leaks: R3-I3 and EXP-01. |
| Archive holder | Photos deleted after the export | **EXP-01**: they stay in the finished zip on the server and can be downloaded. |
| Repo reader | Secrets: `.env`, DBs, keys, `sk-ant-`, `ghp_`, AWS, private keys, high-entropy strings | Clean in the whole history. Every token and password is a placeholder or a test value. `.env.example` has empty secrets. |
| Repo reader | Private hostnames, personal data, local paths | **REPO-01**: the owner's private hostname is in the history. **REPO-02**: the real party name, Instagram handles and local paths were in the tree and are in the history. |
| Repo reader | Screenshots | No QR code, no token, no URL bar. The `wave2-gp` shots show the real party name and handles (REPO-02). |
| Repo reader | CI | Holds. `push` / `pull_request` only (no `pull_request_target`), `contents: read`, no secrets, no artifacts, no untrusted `${{ }}` in `run:`. |
| Docker image | What is inside | Holds. The `.dockerignore` allow-list ships `backend/src` and the `frontend/dist` build: no tests, no `.env`, no `*.db`, no source maps. The image runs as uid 10001. Gap: `frontend/.env.local` would enter the build stage (Low, never happened). |
| Logs | Tokens and passwords | Holds in the app (`t=***`, SEC-07). Not under the app's control: a reverse proxy's access log keeps the full `?t=` URL (R3-I5). |
| Secrets | `/api/admin/settings`, wall config, poster, overview, analysis, audit | Holds. No hash, password, secret key or token in any of them. Full tokens appear only in `/api/admin/codes*` and the admin stream. |
| Secrets | The analysis worker process | **ENV-01**: it inherited `VB_SECRET_KEY` and the admin password. Fixed. |
| Sessions | Admin and wall session fixation or theft | Holds. Both are random and signed, set only after a correct password; the admin cookie is `SameSite=Strict`. A planted admin or wall cookie only logs the victim into the attacker's own session. |
| Caching | Media | `private, max-age=86400` on `/media` and `/livewall/media`. The API is `no-store`, HTML is `private, no-cache`, and the `?t=` 303 is `no-store`. Browser copies after a hide: R2-I5. |
| SSE | The wall stream | A wall cookie or an admin session is required. History replay can carry the metadata of photos that were later removed (R3-I6). |

### Findings

#### REPO-01 · Medium · confirmed · open (owner): the owner's private hostname is in the public history

**Where.** Commits `427dbf0` (`tests/blockerlists.py`, as `HOST`/`BASE`) and `7d5c900`
(`docs/overhaul/analysis/test-suite-map.md`). Both are on `origin/main`. Later commits
(`381e342`, `9b60ec2`) replaced the host in the tree, so the tree is clean. The history is
not.

**Impact.**
- It names the owner's own server, which other services run on, and ties it to this
  project.
- It breaks the project's rule that private domains never appear in the public repo.

It holds no credentials. The hostname is deliberately not repeated here.

**Fix (owner, not possible on a branch).**
1. Run one `git filter-repo` pass. Use `--replace-text` with a file that maps the hostname
   to `party.example.com`, and add the replacements from REPO-02 (the party name, the
   handles, the local paths) in the same pass.
2. For the screenshots, either add
   `--path docs/overhaul/design/shots/wave2-gp --invert-paths` or replace the 20 images
   with demo shots.
3. Force-push `main`.
4. Delete or rebase the local branches and worktrees that still carry the old commits.
   There are 40 refs; pushing any one of them would publish the history again.
5. GitHub keeps unreachable commits reachable by their SHA for a while. If that matters,
   ask GitHub Support to purge cached views.

#### REPO-02 · Low · confirmed · fixed in the tree (`6178172`), history open: real party name, handles and local paths

**What.**
- The real party name with its date, and the Instagram handles of the host
  and a guest. They were in test fixtures, the UI gallery, the design mockups and the UX
  audit, and they are visible in 20 screenshots under
  `docs/overhaul/design/shots/wave2-gp/`.
- `REPORT.md` already listed them as real and asked for a history rewrite before the
  first push. That did not happen.
- The analysis docs named the local home directory, the Claude session folder and
  scratch paths.

**Fix.** The text now uses demo values of the same length. The tests that use them pass:
- Vitest: 4 files;
- `test_tools.py`;
- the e2e files `test_screens_e2e.py` and `test_join_e2e.py`.

The screenshots and the history stay for the REPO-01 rewrite.

#### COOKIE-01 · Low · confirmed · fixed (`2d29a37`): a planted guest id makes a new guest upload into the attacker's identity

**Description.** `vb_uid` is a signed, valid id of a real guest. The attack:
1. The attacker joins and takes their own `vb_uid` value.
2. They put it into a victim's browser before the victim's first scan. Two ways:
   - a sibling subdomain of the party host (any other app on the same registrable domain)
     sets it with `Domain=`;
   - on the party Wi-Fi, before the browser has an HSTS entry for the host, the attacker
     answers any plain-http request to the host with a `Set-Cookie`.
3. The victim scans, and `/api/identify` returns the attacker's identity: no join sheet,
   the attacker's pseudonym.
4. Every photo the victim takes becomes the attacker's. The attacker sees all of them in
   `/api/me/photos` and under `/media`, including photos the wall never shows and photos
   an admin hid.

The other cookies give nothing when planted:
- `vb_access` only grants party access;
- a valid `vb_admin` or `vb_wall` value would only log the victim into the attacker's
  own session;
- `vb_vid` only feeds statistics.

**Repro** (`p3_fixation.py`, http):
```python
att = client("10.1.0.1"); uid = join(att)["uid_token"]
vic = client("10.1.0.2"); vic.cookies.set("vb_uid", uid); access(vic)
vic.post("/api/identify", json={...})  # -> state ok, user "Durstige Robbe #3" (the attacker)
pid = upload(vic).json()["photo"]["id"]
att.get(f"/media/{pid}")               # -> 200: the attacker gets the victim's photo
```

**Fix.** Where cookies are Secure (`cookie_secure()`), the guest id is set and read only
as **`__Host-vb_uid`**. Browsers accept a `__Host-` cookie only when this exact host set it
over TLS, with `Secure`, `Path=/` and no `Domain`. Neither the sibling subdomain nor the
plain-http answer can set it, and the plain `vb_uid` is never read on https.
- Plain-http setups (LAN) keep `vb_uid`, since browsers drop Secure cookies there.
- Guests who still have the old cookie are recognised by the localStorage copy that
  `/api/identify` already sends (`uid`), and get the new cookie. Nobody loses their
  identity on the update.

Live re-run behind `X-Forwarded-Proto: https`: a planted `vb_uid` gives `needs_consent`;
the prefixed cookie gives `ok`.

Tests: `tests/api/test_security_review3.py` (COOKIE-01 section).

**Residual.** A network attacker can still plant a cookie on a plain-http deployment. That
deployment has no confidentiality anyway (R3-I2).

#### ENV-01 · Low · fixed (`e000ec1`): the analysis worker inherited the app's secrets

**Description.** `Supervisor._child_env` copied the whole environment into the worker:
`VB_SECRET_KEY`, `VB_ADMIN_PASSWORD` and `VB_PARTY_TOKEN`. Review 2 recorded this as
R2-I3. The worker decodes stored photos with native ML code (mediapipe, onnxruntime,
OpenCV), the largest decoder surface in the app, and needs none of those values. Two
consequences:
- A memory-corruption bug there gets the cookie-signing key: it could forge access, guest
  and wall cookies (admin sessions are random tokens, not signed values).
- Once the Anthropic key is stored encrypted with a key derived from `VB_SECRET_KEY`, it
  would get that key too.

**Fix.** The worker gets the environment without `VB_SECRET_KEY`, `VB_ADMIN_PASSWORD`,
`VB_PARTY_TOKEN` and any `*_API_KEY` or `*_SECRET` variable (`supervisor.is_secret_env`).
Test: `test_the_worker_inherits_no_secrets`.

#### ARCH-02 · Low · fixed (`e000ec1`), preparation: secrets stored in `settings` would have gone into archives

**Description.** The archive scrub dropped only `admin.password` and `x.*.password`. A new
secret in `settings`, such as the Anthropic key, would have landed in every archive's DB
copy.

**Fix.** A naming rule. Every settings key that ends in **`.secret`** is deleted from the
copy, like the password hashes. README.txt says so. Test:
`test_snapshot_drops_every_secret_setting`.

#### EXP-01 · Low · confirmed · accepted with a follow-up: finished exports keep photos deleted later

**Description.** "Endgültig löschen" removes the photo, its thumbnail and the wall's
1280 px copy. But an archive (or timelapse) finished earlier stays in `<data>/exports/`.
Up to 10 are kept, and each can still be downloaded with the deleted photo in it.

**Repro** (`p2_archive.py`): export, delete the photo, download the export again → `200`,
and the photo's file and CSV row are inside.

Only an admin can download exports, so nobody gains access they did not have. But a
deletion made for a guest's sake (a privacy request, an embarrassing photo) is not
complete while an older export exists.

**Why not fixed here.** Deleting exports automatically would silently throw away the
host's final archive. The admin decides better, and that needs a frontend change.

**Follow-up.** The delete dialog (`DeletePhotosDialog`) should say "Fertige Exporte
enthalten das Foto noch" and link to Export, or offer "auch Exporte löschen, die es
enthalten". The jobs have `created_at`; a photo is in a job when it was created before it.

#### Info

- **R3-I1 · no Host allow-list (DNS rebinding).**
  - The CSRF check compares `Origin` with the request's own `Host`. A page that rebinds its
    own name to the server's address passes that check.
  - It brings no victim cookies, so it can only try logins. From loopback (a browser on
    the server machine itself, e.g. the party laptop running `virtubooth serve`) those
    are exempt from the global lock (SEC-01), but the per-IP limit of 20 per hour still
    applies.
  - Hardening, if wanted: answer 421 to `Host` values that are not an IP literal,
    `localhost`, the host of `VB_PUBLIC_BASE_URL` or of `VB_ALLOWED_ORIGINS`.
- **R3-I2 · plain http.**
  - Supported for LAN tests, but everything is readable on the Wi-Fi: the token, cookies,
    and the admin and wall passwords.
  - Phones don't open the camera on http (except `localhost`), so a real party runs https.
  - Worth a line in DEPLOY.md: "on http, anyone on the Wi-Fi can read the admin password".
- **R3-I3 · README.txt names the server's data dir.**
  - "Created … from `<absolute data dir>`" ends up in every archive. In Docker that is
    `/data`; on a laptop it is the host's home path.
  - Harmless, but it could say only the folder name.
- **R3-I4 · an admin session on the TV is the whole admin.**
  - `wall_auth` accepts an admin session everywhere. A host who opens `/livewall` on the
    TV while logged in as admin (instead of using the wall password) leaves a 12-hour admin
    session in a browser that guests can touch.
  - Worth a hint in the wall admin: "Für den Fernseher das Wall-Passwort nutzen, nicht den
    Admin-Login".
- **R3-I5 · reverse-proxy access logs keep the token.**
  - The app masks `?t=`, but nginx (on by default), Caddy (when enabled) and Traefik
    (when enabled) log the full request URL of every scan.
  - DEPLOY.md could suggest a log format without the query string, or turning access logs
    off for the virtual host.
- **R3-I6 · wall event replay keeps metadata of removed photos.**
  - `?since=` / `Last-Event-ID` replay up to 1024 wall events. A `photo.add` before its
    `photo.remove` still carries the pseudonym, the time and the facts of a photo that
    was later hidden or deleted.
  - The image itself answers 404.
  - Only wall-cookie holders and admins can read the stream.

### Status

| ID | Severity | Status | Commit |
|---|---|---|---|
| REPO-01 | Medium | open: history rewrite by the owner | – |
| REPO-02 | Low | fixed in the tree; history and screenshots with REPO-01 | `6178172` |
| COOKIE-01 | Low | fixed | `2d29a37` |
| ENV-01 | Low | fixed | `e000ec1` |
| ARCH-02 | Low | fixed (preparation) | `e000ec1` |
| EXP-01 | Low | accepted; frontend follow-up | – |
| R3-I1 … R3-I6 | Info | notes | – |

**Tests run (targeted).**
- Backend, `uv run pytest -n 4`:
  - `test_security_review3`
  - `test_security_fixes`
  - `test_core_access`
  - `test_code_access`
  - `test_admin_api`
  - `test_core_admin_auth`
  - `test_admin_upload_controls`
  - `test_here`
  - `test_admin_dashboard`
  - `test_code_guests`
  - `test_admin_exports`
  - `tests/unit/test_enrich_supervisor`
  - `tests/unit/test_tools`

  All passed.
- Vitest: the 4 changed test files.
- e2e (Chromium): `test_screens_e2e.py` and `test_join_e2e.py`.
- `ruff check`, `ruff format --check`, `mypy`, `tsc -b` and prettier are clean.
- No OpenAPI change.

### Accepted risks

- **EXP-01:** older exports keep deleted photos until the admin deletes them (see the
  follow-up).
- **Plain-http deployments (R3-I2):** no protection against the Wi-Fi, by nature.
  COOKIE-01's fix only applies with Secure cookies.
- **The QR overlay** (R2-I2) and **QR tokens in the archive** (review 2) stay as decided.
- **Repository history (REPO-01/02):** open until the owner rewrites it. A branch commit
  cannot remove it.

### Storing an API key (notes for the Anthropic key)

These rules let the coming Anthropic API key pass every vector above. Items 1 to 3 are
already enforced by this review's changes.

1. **Key name.** Store it under a `settings` key that ends in `.secret`, for example
   `ai.anthropic.secret`. The archive scrub then drops it (ARCH-02, tested). Never use an
   `x.<id>.config` blob or any other key.
2. **The worker.** It must never see the key or `VB_SECRET_KEY` (ENV-01). If the analysis
   worker ever calls Claude itself:
   - hand it the plaintext key per job over its stdin pipe, never through the environment
     or a file;
   - better, let the app make the API call.
3. **Variable names.** Any env variable named `*_API_KEY` or `*_SECRET` is already kept
   from the worker.
4. **Encryption.**
   - Use AES-256-GCM from `cryptography` (a new runtime dependency: pin it exactly and let
     `uv.lock` hash it).
   - The key comes from HKDF-SHA256 over `VB_SECRET_KEY`, with `info=b"virtubooth
     settings-secret v1"` and a fixed salt. Never use `VB_SECRET_KEY` directly; use a
     separate purpose like the `Signer` does.
   - Store `{"v": 1, "nonce": <96-bit random, b64>, "ct": <b64>, "last4": "…abcd",
     "set_at", "by"}`, with `aad = b"ai.anthropic.secret|v1"` so a ciphertext can't be
     moved to another key.
   - Then a copied `virtubooth.db` or a volume backup alone does not reveal the key; it
     also needs the env.
5. **Rotating `VB_SECRET_KEY`.**
   - Decryption fails (`InvalidTag`). Treat that as "no key stored": state `key_unreadable`
     in the admin, log one warning without the value, and ask the host to enter it again.
   - Never fall back to the plaintext.
6. **A write-only API.**
   - `PUT` takes the key; `GET` returns only `{set, last4, set_at, by}`; `DELETE` removes
     it. Never return the key, not even to the admin.
   - The input model uses `SecretStr` (no echo in `repr` or logs). The 422 handler already
     answers a generic `invalid_request`; keep it that way, because FastAPI's default
     validation error echoes the input.
   - Validate `^sk-ant-[A-Za-z0-9_-]{20,200}$`.
   - All routes sit behind `require_admin`, under `/api/admin/…` (CSRF and `no-store`
     come for free).
7. **Never in events, audit or logs.**
   - The admin SSE event says only `{"set": true, "last4": …}`.
   - Audit `ai.key_set` / `ai.key_removed` with `last4` only.
   - Add `sk-ant-[A-Za-z0-9_-]+` → `sk-ant-***` to `core/logs.py` as defence in depth (the
     access log filter only touches `uvicorn.access`; add a root-logger filter too).
   - Never log `str(exc)` of an HTTP client error that may include request headers, and
     never `repr()` the client.
8. **Outbound calls.**
   - Use a fixed base URL `https://api.anthropic.com`. It must not be admin-configurable:
     a settable base URL is a key-exfiltration and SSRF primitive.
   - Set a timeout and no redirects to other hosts. Only the app process calls out.
9. **Use and memory.** Decrypt per use, keep the plaintext in a local variable only, and
   don't cache it on long-lived objects (`Core`, hubs, the bus).
10. **Consent and privacy.**
    - The join text promises today: "Nichts davon verlässt den Server"
      (`WALL_ANALYSIS_TEXT`). Sending photos to Anthropic breaks that promise, so:
      - change the text;
      - bump `VB_CONSENT_VERSION`;
      - honour `analysis_opt_out` (never send an opted-out guest's photo);
      - send only visible, non-hidden photos past the wall delay.
    - Say in the admin what leaves the server.
11. **The frontend field.**
    - `type="password"` and `autocomplete="off"`; never prefill it.
    - Show `…last4` and "gesetzt am …".
    - A "Schlüssel prüfen" button that makes one cheap API call on the server, rate
      limited, which reports only ok, invalid or no credit.
12. **Tests to add with it.**
    - The key never appears in: `GET` answers, the admin stream, the audit list, the
      archive DB copy (the marker test pattern of ARCH-02), the log output (caplog), or a
      422 answer.
    - After a secret-key change, the state is "unreadable", not a 500.

## Review 3, pass 2: the external-AI key and LLM path (2026-10-15)

Second, short pass at the end of the night batch (INT2) over the new key/LLM path,
the public-address probe and prompt injection. Full notes:
`.worktrees/_plans/night/int2/SECURITY-2.md`. No open High or Medium finding.

| ID | Severity | Finding | Status |
|---|---|---|---|
| LLM-01 | Medium | A verdict naming a guest stayed on the wall after the guest opted out of external AI (or was banned) | fixed: the screen drops it at once |
| LLM-02 | Medium | Polls named guests by „@handle“ even while the wall hides handles; the verdict text lands on the wall | fixed: the wall's naming rule |
| LLM-03 | Low | Key redaction only on loggers that existed at start | fixed: also on the root and uvicorn handlers |
| ADDR-01 | Low | The public-address probe echoed a redirect's full `Location` (path/query of any, maybe internal, server) | fixed: origin only |
| ADDR-02 | Low | The probe lets an admin tell reachable from unreachable hosts (no body is shown) | accepted (admin-only) |

Checked and fine: the key is in no response schema, log, audit entry, stored error or
archive (the scrub drops `x.llm.key` and every `*.secret` key); AES-256-GCM with a fresh
96-bit nonce per write and HKDF per PLAN-NIGHT N11; every `/llm/*` and `/test-image`
mutation is admin-only and Origin-checked; `/test-image` is size-capped, JPEG-only and
6/min; guest text reaches a provider only JSON-quoted inside a data block, answers are
validated and length-capped, verdict photo refs must be ones that were sent; a test
records every provider call over detection, poll and verdict with mixed guests and finds
nothing of opted-out or banned guests or hidden photos.
