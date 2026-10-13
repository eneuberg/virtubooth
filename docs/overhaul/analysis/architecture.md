# virtubooth: phase 1 architecture analysis (overhaul reference)

I analysed `.worktrees/overhaul` at commit `1d6b5eb`, which is identical to `main`. Nothing in the repo was modified.

**How the facts were checked.**
- I read every backend module, the core frontend SDK and both extension frontends myself.
- I confirmed the exact response shapes by calling the real app with FastAPI's `TestClient`. It ran in a scratch data directory with bytecode writing off, so no repo files were touched.
- Two read-only helpers produced the admin UI inventory and the test-suite map. Their full reports are much longer than the summaries in §3.9 and §6. **Save them verbatim as appendices**, because the rewrite must not lose anything in them:
  - **Appendix A, admin UI inventory (about 1160 lines):** `/home/erikli/.claude/projects/-home-erikli-a-personal-aaa-doingthings-random-projects/c8c156ec-0ba7-4a87-baaa-c6c050bea40f/tool-results/toolu_01DuJianoMgwYYwuw7B7PUWF.txt`. Suggested name: `docs/overhaul/analysis/admin-ui-inventory.md`.
  - **Appendix B, test-suite map (about 1200 lines):** `/home/erikli/.claude/projects/-home-erikli-a-personal-aaa-doingthings-random-projects/c8c156ec-0ba7-4a87-baaa-c6c050bea40f/tool-results/toolu_01CfXJR5wGpk4TnbtQRa3acN.txt`. Suggested name: `docs/overhaul/analysis/test-suite-map.md`.

---

## 0. Key takeaways

1. **The backend is already layered better than its folder suggests.** The problems are:
   - A 726-line god `repo.py`.
   - View serialisation (`admin_view` / `guest_view`) lives on the domain dataclasses.
   - Business logic sits in route handlers: the upload pipeline, ban plus auto-ban release, and join.
   - Raw SQL is spread over `admin/queries.py` and `tools/_common.py`.
   - Pydantic models exist for requests only. There are no response models, and OpenAPI is off.
   
   These are fixable without changing any behaviour.
2. **The API surface is small and stable:**
   - 6 guest JSON routes, `/media`, `/healthz`.
   - 3 admin-auth routes and 22 admin routes, one of which is SSE.
   - Page routes.
   
   Its JSON shapes are fully pinned by about 190 API tests that survive a frontend rewrite unchanged.
3. **The frontend is 6.5k LOC of JS, 2.3k of CSS and 0.4k of HTML** across 6 page entries (home, beer, booth, admin login, live, manage, user) plus 2 static server pages (gate, 404).
   - The camera, render and outbox code is framework-agnostic already. It should be ported to TypeScript nearly 1:1.
   - The UI code (dialogs, state, re-rendering) is where a framework helps.
4. **The hard constraints for the framework and build:**
   - Strict CSP (`script-src 'self'`, `style-src 'self'`). There can be no runtime `<style>` injection and no inline scripts.
   - Content-blocker-safe file, URL and class names. Hashed bundle names can trip the `ads?[-_./]` regex; see §5.
   - A classic, non-module `loader.js` watchdog.
   - Server-side gating of every page. The gate page returns HTTP 404, and admin pages redirect with `next`.
   - Single process, SSE.
5. **The e2e suite (123 functions) is DOM-contract-based.** It uses test ids, roles, German strings, `data-*` state attributes and a few classes. About 101 functions survive if the new UI keeps that contract; 19 need rewriting.
   - Unit and API tests: 211 functions / 306 cases.
   - Static-source tests to retarget: 23 functions.
6. **Bugs found during analysis** (keep or fix deliberately):
   - **SSE subscriber overflow** leaves a live-looking stream that never delivers events again (§7).
   - **Admin `goLogin()` drops `?id=`** (§3.9).
   - **The uploads sheet has no focus trap.**
   - **`next` cursor:** returned even when the page is exactly full.
   - **Payload inconsistency:** `user.uploads_changed` payloads lack `auto_banned`.

---

## 1. Inventory and responsibilities

### 1.1 Backend (Python, `virtubooth/`, 5,267 LOC)

| File | LOC | Responsibility |
|---|---|---|
| `__init__.py` | 1 | package docstring |
| `__main__.py` | 71 | CLI `virtubooth serve` (uvicorn factory, `proxy_headers`, `forwarded_allow_ips`, one worker, `timeout_graceful_shutdown=5`, `server_header=False`) and `gen-env` (random secrets) |
| `app.py` | 105 | `create_app(settings, extensions)`: builds `Core`, the exception handlers (ApiError, 422, HTTP→JSON or gate/404 HTML), routers, `/static` mount, middlewares; `create_app_from_env` |
| `config.py` | 117 | `Settings` frozen dataclass and manual `from_env` (`VB_*`) with validation; `TOKEN_RE` |
| `context.py` | 56 | `Core` (settings, db, repo, bus, signer, limits, extensions); `Limits` (9 `RateLimiter`s) |
| `db.py` | 194 | SQLite schema v1 (`SCHEMA`), v2 (`SCHEMA_V2`), `MIGRATIONS` and a migrator using `PRAGMA user_version`; `Database` (one shared connection, RLock, WAL, `tx()`, `all()`, `one()`) |
| `repo.py` | **726** | **all** data access: users, fingerprints, user and fp bans, upload pauses, the new-guest lock, the stop switch, the settings KV store, photos (insert/list/hide/delete plus file unlink), admin sessions, audit log; also `User`/`Photo` dataclasses with `guest_view`/`admin_view`, `PhotoQuery` |
| `deps.py` | 96 | `get_core`, `has_access`, `guest_from_cookie`, `require_access`, `optional_guest` (unused), `require_guest`, `Admin`, `admin_from_cookie`, `require_admin` |
| `security.py` | 159 | cookie names, CSP and security headers, `Signer` (HMAC), `constant_time_equals`, access cookie value, admin `pw_tag`, `set_cookie`, `client_ip`, `origin_allowed` (CSRF) |
| `middleware.py` | 153 | `GuardMiddleware` (`?t=` entry, CSRF, body-length cap, `/api` request budget); `SecurityHeadersMiddleware` (headers, HSTS, default Cache-Control). Pure ASGI |
| `errors.py` | 67 | `ApiError(status, code, message, headers)` and factories (`scan_qr`, `needs_consent`, `banned`, `uploads_paused`, `uploads_stopped`, `rate_limited`, `not_found`, `bad_request`, `admin_required`) |
| `identity.py` | 228 | `/api/identify`, `/api/join`, `PATCH /api/me`; Instagram normalisation with German error texts; `Fingerprint` sanitising; consent text |
| `admin_auth.py` | 94 | `/api/admin/login`, `/logout`, `/session` |
| `uploads.py` | 189 | `POST /api/x/{ext}/upload`: gating, rate limits, meta parsing, streaming size cap, `process_jpeg`, file writes (atomic), DB insert, `on_upload`, event; `guest_photo_view` |
| `media.py` | 53 | `GET /media/{public_id}` (owner or admin only); `photo_file_response` |
| `pages.py` | 126 | `/healthz`, `/`, `/api/extensions` (an API route in pages.py), `/x/{ext}`, `/x/{ext}/{rel}`, `/admin*` pages and assets; `safe_file`; gate/404 HTML |
| `events.py` | 108 | `EventBus` (asyncio queues, thread-safe publish, drops slow subscribers); `format_sse`, `sse_stream`, `sse_response` (unused by core) |
| `images.py` | 67 | `process_jpeg`: magic bytes, format, size and exact-size checks, EXIF transpose, re-encode, 400 px thumbnail; `MAX_IMAGE_PIXELS=25M` |
| `names.py` | 26 | `pseudonym(id)` → "Tanzender Waschbär #17" (gender-correct adjective endings) |
| `ratelimit.py` | 55 | in-memory token bucket (`hit`, `available`, `retry_after`, `reset`, sweep every 5 min) |
| `logs.py` | 28 | uvicorn access-log filter: masks `?t=`/`&t=` as `***` and drops `/healthz` |
| `extension.py` | 128 | `UploadPolicy`, `UploadContext`, `Extension` (`public_view`/`admin_view`), `validate_extension`, `discover_extensions` (pkgutil, `VB_EXTENSIONS` order) |
| `extensions/__init__.py` | 1 | namespace for extension packages |
| `extensions/beer/__init__.py` | 79 | Beer Cam: `UploadPolicy` (exactly 1080×1440, meta vessel/facing), `GET /stats`, `on_upload` → `beer_number`, `total` |
| `extensions/booth/__init__.py` | 85 | Fotobox: loads `static/filters.json` (`load_filters`), `UploadPolicy` (exactly 1080×1440, meta filter/facing), `on_upload` → `booth_number`; no router |
| `admin/__init__.py` | 1 | docstring |
| `admin/api.py` | **517** | 17 admin routes (photos, bulk, users, ban/unban plus auto-ban release, device bans, stats, Instagram, audit, extensions, SSE); includes `upload_controls.router` |
| `admin/queries.py` | 238 | read-only raw-SQL aggregates (stats, counts, fingerprint peers, fp bans, auto-ban sources/release set, Instagram handles, audit page); `AUTO_BAN_REASON` |
| `admin/upload_controls.py` | 150 | `/upload-stop`, `/upload-pause`, `/users/{id}/uploads`; state views; events |
| `tools/__init__.py` | 11 | docstring |
| `tools/_common.py` | 144 | `ToolError`, `run()`, data-dir resolution, `open_repo` (runs migrations), `iter_photos` paging, `scratch_parent` (never /tmp), `photo_counts` (raw SQL) |
| `tools/export.py` | 413 | `.tar.gz` export: photos (hidden/ subfolder), CSVs with formula escaping, Instagram tag list, SQLite backup-API snapshot, README |
| `tools/qr.py` | 289 | QR SVG/PNG (segno, level H) plus a printable A4 `qr-sheet.html`; never prints the token |
| `tools/timelapse.py` | 492 | ffmpeg timelapse: collect, letterbox odd frames (Pillow), numbered symlinks, `tmix` crossfade, progress parsing, dry run |

### 1.2 Frontend (6,476 LOC JS / 2,264 CSS / 395 HTML)

| File | LOC | Responsibility |
|---|---|---|
| `static/core/vb.js` | **790** | Guest SDK. Re-exports `camera.js`. Sets `window.__vbReady`. `h()` DOM builder. Debug panel. `api()` / `ApiError`. Dialog focus trap (`holdFocus`). Join dialog (`boot`/`askConsent`). Instagram editor (`mountUserChip`/`editInstagram`). Upload pause/stop hint plus 30 s recheck. `uploadJpeg` (XHR with progress). `canvasToJpeg`, `saveImage`, `toast`, `showNotice`, `fatal`, `flash`, `vibrate`, `confetti`. Lazy `getFingerprint` with fallback |
| `static/core/camera.js` | 199 | `openCamera` controller, `captureFrame` (cover crop plus mirror), `CameraError`, `cameraErrorMessage` (German, iOS/touch/desktop/in-app variants), `isIOS`, `isInAppBrowser` |
| `static/core/device.js` | 86 | device traits ("fingerprint"), loaded only through dynamic `import()` |
| `static/core/loader.js` | 35 | classic script watchdog: after 6 s without `__vbReady`, shows the "Die Seite startet nicht" notice |
| `static/core/home.html` / `.js` / `.css` | 26 / 30 / 26 | home page: party name, user chip, extension tiles |
| `static/core/gate.html`, `notfound.html` | 19 / 19 | server-returned 404 pages (no JS) |
| `static/core/vb.css` | 499 | tokens `--vb-*`, buttons, chip, input, stage, scrim/sheet, notice, toast, pause chip, progress, spinner, confetti, flash, debug, reduced motion |
| `static/core/icon.svg` | 1 | favicon |
| `extensions/beer/static/index.html` | 100 | Beer Cam markup (static DOM, test ids) |
| `extensions/beer/static/beer.js` | 468 | Beer Cam page logic (state machine, upload/retry, success, keyboard, stats poll) |
| `extensions/beer/static/shapes.js` | 100 | bottle/cup SVG outline paths in 1080×1440 space; overlay and icon builders |
| `extensions/beer/static/beer.css` | 543 | layout (container-query 3:4 box, landscape grid, short screens) |
| `extensions/booth/static/index.html` | 81 | Fotobox markup |
| `extensions/booth/static/booth.js` | **787** | Fotobox page: render loop, filter strip, gestures, countdown, result screen, background upload, outbox UI, leave dialog, keyboard |
| `extensions/booth/static/renderer.js` | 400 | WebGL1 renderer (shader prelude, FBO capture) and Canvas2D fallback |
| `extensions/booth/static/filters.js` | 456 | 10 filter implementations (GLSL, optional CPU fallback, overlays), `buildFilterList`, `drawOverlay` |
| `extensions/booth/static/overlays.js` | 196 | Canvas2D drawing helpers, seeded PRNG, 5×7 pixel font, dates |
| `extensions/booth/static/outbox.js` | 85 | IndexedDB outbox (best effort) |
| `extensions/booth/static/filters.json` | 15 | filter catalogue (ids, German names, icons, strip order); **read by the backend too** |
| `extensions/booth/static/booth.css` | 429 | layout |
| `admin/static/*.html` | 150 | login, live, manage, user shells |
| `admin/static/assets/admin.js` | **925** | shared admin library (aapi, formatting, badges, PhotoCollection, Lightbox, confirmDialog, focus/inert helpers, SSE client, widgets) |
| `admin/static/assets/manage.js` | **905** | manage screen, 5 tabs |
| `admin/static/assets/user.js` | 397 | guest detail page |
| `admin/static/assets/uploadcontrols.js` | 390 | uploads chip and sheet, guest uploads panel, paused badges |
| `admin/static/assets/live.js` | 181 | live screen |
| `admin/static/assets/login.js` | 46 | login, `safeNext` |
| `admin/static/assets/admin.css`, `uploadcontrols.css` | 620 / 147 | admin styles |

### 1.3 Ops and tests

| Area | Files |
|---|---|
| Ops | `Dockerfile` (80: uv build stage, then python-slim runtime with ffmpeg, uid 10001, healthcheck, `CMD virtubooth serve`) · `compose.yaml` (96: read-only rootfs, tmpfs /tmp, cap_drop ALL, limits, named volume, `127.0.0.1:8000` publish) · `docker-compose.coolify.yaml` (66: generated secrets via `SERVICE_*`, no published port, forwarded IP ranges) · `.dockerignore` (allowlist: pyproject, uv.lock, README, `virtubooth/`) · `.env.example` (119) · `pyproject.toml` (hatchling, deps fastapi/uvicorn/pillow/segno/tzdata; dev pytest/httpx2/playwright 1.63.0; `addopts -m 'not e2e'`) |
| Tests | Unit/API 3,680 LOC in 11 files; e2e 3,944 LOC in 9 files plus conftests 509; `blockerlists.py` 1,116 plus `fixtures/blocker_rules.txt` 455 |
| Docs | README 445, ARCHITECTURE 243, DEPLOY 370, PLAN 22, REQUIREMENTS 35 |

### 1.4 Hot spots

- **Largest files:** admin.js 925, manage.js 905, vb.js 790, booth.js 787, repo.py 726, admin/api.py 517, timelapse.py 492, beer.js 468, filters.js 456.
- **Most coupled:**
  - `repo.py` is imported by deps, identity, uploads, media, admin, context and tools; 40 of its methods are used directly by tests.
  - `context.Core` is passed everywhere.
  - `vb.js` is imported by every page. It has import side effects: `__vbReady`, global `visibilitychange` and `onUserChange` listeners, and the debug panel.
  - `admin.js` is used by every admin module.
  - `middleware.py` imports `pages.gate_page` and `deps.admin_from_cookie`.
- **Duplicated code:**
  - **beer.js and booth.js share page scaffolding:** `storageGet`/`storageSet` (also in vb.js), a local `fatal`, `showBanned`, `BANNED_TEXT`, `dialogOpen`, `isTyping`, `retryAfter`, `renderRetry`, the rate-limit texts, and the reload and home buttons.
  - **Six modal implementations:**
    - vb `holdFocus` (join, Instagram)
    - vb `explainUploadHint` (its own Esc handling, no trap)
    - booth leave sheet (own Esc, no trap)
    - admin `confirmDialog` (trap plus inert)
    - admin uploads sheet (no trap)
    - admin `Lightbox` (trap plus inert)
  - **Other frontend duplicates:**
    - `sha256Hex` appears in vb.js and device.js, with different FNV constants in the fallback.
    - `isIOS` appears in camera.js and again inline in `saveImage`.
  - **Backend duplicates:**
    - `_user_or_404` is in both `admin/api.py` and `upload_controls.py`; so is `MAX_ID`.
    - The photo-id regex is defined twice: `media.PUBLIC_ID_RE` and `admin.PHOTO_ID_PATTERN`.
    - The extension-id regex is defined three times: `EXT_ID_RE`, middleware `_UPLOAD_PATH` and `admin.EXT_ID_PATTERN`.
    - `"Gerät gesperrt (Fingerprint)"` is a string literal in `identity.py` and `queries.AUTO_BAN_REASON`.
    - 1080×1440 is defined in 6 places (beer py, booth py, beer.js, shapes.js, renderer.js, tests).
    - `FACINGS` is defined twice.
    - `count_photos` exists in repo and queries.
    - `_user_ref` is built twice (api.py and queries.py).
    - The SSE `StreamingResponse` headers are written twice (`events.sse_response` and `admin/api.events`).
  - **Admin JS duplicates:** see Appendix A §16. "Load more" exists in 4 variants with 3 cursor styles; the resync window logic is written twice; there are 3 `onToggle` copies and 2 unban flows.

---

## 2. Complete API contract

### 2.1 Conventions (apply to every route)

**Error envelope.** Every error is JSON `{"error": <code>, "message": <German text, show as-is>}`. Shapes for the framework-level cases:

| Case | Status | Body |
|---|---|---|
| Pydantic validation (body, query, path) | 422 | `{"error":"invalid_request","message":"Ungültige Anfrage."}` |
| Unknown `/api/*` path | 404 | `{"error":"http_404","message":"Not Found"}`. This is **not** `scan_qr`, even without access. |
| Wrong method | 405 | `{"error":"http_405","message":"Method Not Allowed"}` |
| Any non-404 HTTPException | as raised | `http_<status>` |
| Non-API 404, no access | 404 | `gate.html` |
| Non-API 404, with access | 404 | `notfound.html` |
| `ApiError` on a non-`/api` path (`/media`) | as raised | still JSON |

**Middleware (`GuardMiddleware`, outermost after the security headers).** For each HTTP request, in this order:

1. **Token entry.** Applies to `GET` with a `t` query parameter whose path does not start with `/api/`, `/admin`, `/static/`, `/media/` or `/healthz`.
   - Valid token (constant-time compare): **303** to the same path. The path is normalised to exactly one leading slash, so `//evil.example/` becomes `/evil.example/`. The other query parameters are kept and only `t` is removed. The response sets the `vb_access` cookie.
   - Invalid token: **404** `gate.html`, with no cookie.
2. **CSRF.** Any `POST`/`PUT`/`PATCH`/`DELETE` on **any** path needs `Origin`, or `Referer` as a fallback. It must equal the request's `Host` (lower-cased; default ports 80/443 dropped) or be listed in `VB_ALLOWED_ORIGINS`. Otherwise: **403** `{"error":"bad_origin","message":"Anfrage von fremder Seite abgelehnt."}`. `Origin: null` or a missing header fails.
3. **Body cap.** Applies to unsafe methods except `^/api/x/[a-z][a-z0-9-]{1,30}/upload$`.
   - A `Transfer-Encoding` header or a non-numeric `Content-Length` gives **411** `{"error":"length_required","message":"Ungültige Anfrage."}`.
   - `Content-Length` > 65,536 gives **413** `{"error":"too_large","message":"Anfrage zu groß."}`.
   - A missing Content-Length counts as 0.
4. **API budget** for `/api/*`:
   - A valid admin session on `/api/admin/*` is exempt.
   - Otherwise, if the signed `vb_uid` cookie is valid, the bucket is `api_guest` (key `uid:<public_id>`, 300/min).
   - Otherwise the bucket is `api_ip` (key = client IP, 1200/min).
   - Over budget: **429** `{"error":"rate_limited","message":"Langsam! Zu viele Anfragen. Warte kurz."}` with `Retry-After: <int s ≥1>`.

**Response headers (`SecurityHeadersMiddleware`, `setdefault`).**
- Headers:
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: DENY`
  - `Permissions-Policy: camera=(self), microphone=(), geolocation=(), payment=(), usb=()`
  - `Cross-Origin-Opener-Policy: same-origin`
  - `Cross-Origin-Resource-Policy: same-origin`
  - `Strict-Transport-Security: max-age=31536000`, only when the ASGI scheme is https (that is, a trusted `X-Forwarded-Proto`)
- `Cache-Control`, unless the route set it: `/api/*` → `no-store`, everything else `no-cache` (ETag revalidation). Media uses `private, max-age=86400`; SSE uses `no-store` plus `X-Accel-Buffering: no`.

**Cookies.** All have `Path=/` and `HttpOnly`. `Secure` is set if `VB_COOKIE_SECURE=true`, or if it is `auto` and (the request is https or `VB_PUBLIC_BASE_URL` starts with `https://`).

| Name | Value | SameSite | Max-Age | Set by | Read by |
|---|---|---|---|---|---|
| `vb_access` | `b64url(HMAC_SHA256(secret, "access|"+party_token))` (rotating the token invalidates it) | Lax | 30 d | token entry | `has_access` (pages, `require_access`, media, 404 page choice) |
| `vb_uid` | `<public_id>.<b64url HMAC("uid|"+public_id)>`; the same string is returned as `uid_token` | Lax | 30 d | identify (known), join | `require_guest`, media, the API budget key |
| `vb_admin` | `token_urlsafe(32)`. The DB stores the sha256, `expires_at` and `pw_tag = mac("admin-pw", password)[:22]`. | **Strict** | `VB_ADMIN_SESSION_HOURS`×3600 (12 h) | login | `require_admin`, media, the API budget exemption, admin pages |

Logout calls `delete_cookie("vb_admin")`. That cookie is emitted with `SameSite=lax`, without `HttpOnly`, and with `Max-Age=0`; this is cosmetic.

**Timestamps.** Always ISO-8601 UTC with milliseconds and `+00:00`, e.g. `2026-10-13T01:39:22.113+00:00`. They compare correctly as strings; admin.js relies on that.

**Auth levels used below:**
- **public**: no requirement.
- **access**: valid `vb_access`; otherwise 404 `scan_qr` "Bitte scanne den QR-Code auf der Party, so geht das leider nicht."
- **guest**: access, plus a valid `vb_uid` user (otherwise 401 `needs_consent` "Bitte bestätige zuerst kurz die Hinweise."), plus not banned (otherwise 403 `banned` "Dieses Gerät wurde für Uploads gesperrt.").
- **admin**: valid `vb_admin` session; otherwise 401 `admin_required` "Bitte als Admin anmelden."

### 2.2 Shared object schemas (TypeScript notation)

```ts
type ISO = string;                       // UTC ISO-8601 with ms
type PublicPhotoId = string;             // ^[A-Za-z0-9_-]{8,32}$ (generated: token_urlsafe(12), never leading "-")
type FpHash = string;                    // ^[0-9a-f]{16,64}$
type Meta = Record<string, string | number | boolean | null>;

interface ApiErrorBody { error: string; message: string }

// guest side
interface GuestUser { name: string; instagram: string | null; banned: boolean; uploads_paused: boolean } // EXACTLY these keys (tested)
interface ConsentInfo {
  version: string; title: string /* "Willkommen bei {party}! 🎉" */; paragraphs: string[] /* 3 */;
  instagram_prompt: string; accept_label: string /* "Alles klar, los geht's! 🍻" */;
  party_name: string; instagram_account: string;
}
interface GuestPhoto { id: PublicPhotoId; extension: string; seq: number; created_at: ISO; width: number; height: number;
  url: string /* /media/{id} */; thumb_url: string /* /media/{id}?thumb=1 */ }
interface PublicExtension { id: string; title: string; emoji: string; tagline: string; url: string /* /x/{id}/ */; uploads: boolean }

// admin side
interface PhotoUser { id: number; name: string; instagram: string | null; banned: boolean; uploads_paused: boolean } // no auto_banned!
interface AdminPhoto {
  id: PublicPhotoId; extension: string; seq: number; created_at: ISO; width: number; height: number; bytes: number;
  meta: Meta; hidden: boolean; hidden_at: ISO | null; hidden_reason: 'admin' | 'ban' | null; deleted: boolean;
  url: string; thumb_url: string; user: PhotoUser;
}
interface AdminUser {                     // User.admin_view()
  id: number; name: string; instagram: string | null; created_at: ISO; last_seen_at: ISO; consent_at: ISO; consent_version: string;
  fp_hash: FpHash | null; fp_components: Record<string, string | number | boolean | null>;
  first_ip: string; last_ip: string; user_agent: string;
  banned: boolean; banned_at: ISO | null; ban_reason: string | null; photo_count: number /* non-deleted */;
  uploads_paused: boolean; uploads_paused_at: ISO | null; uploads_paused_source: 'admin' | 'new_guest_lock' | null;
  uploads_lock_period: number | null;
}
interface AutoBan { fp_hash: FpHash; source_user_id: number | null; source_user_name: string | null }
interface AdminUserView extends AdminUser { auto_banned: boolean; auto_ban: AutoBan | null }  // _user_views()
interface UserRef { id: number; name: string; instagram: string | null; banned: boolean; auto_banned: boolean }
interface StopState { enabled: boolean; since: ISO | null; by: string | null }
interface PauseState { enabled: boolean; since: ISO | null; period: number | null /* null while disabled */; by: string | null;
  affected: number /* still paused by this period; 0 when disabled */; paused_total: number }
interface AdminExtension extends Omit<PublicExtension, 'url'> { url: string | null; meta_labels: Record<string,string>; loaded: boolean }
```

`auto_banned` is true when `banned && ban_reason === "Gerät gesperrt (Fingerprint)"`. `auto_ban` holds the earliest still-existing fingerprint ban among the user's fingerprints, or null.

### 2.3 Page routes and static assets

| Route | Auth | Behaviour |
|---|---|---|
| `GET`/`HEAD /healthz` | public | `{"ok": true}`; filtered out of the access log |
| `GET /` | — | access → `home.html` 200; otherwise `gate.html` **404** |
| `GET /x/{ext_id}` | public | **308** → `/x/{ext_id}/` (no access check) |
| `GET /x/{ext_id}/{rel}` | — | No access → gate 404. Unknown extension → notfound 404. File: `safe_file(ext.static_dir, rel or "index.html")`, which rejects NUL, backslash, any path segment starting with `.`, anything outside the root, and directories; failing that → notfound 404. MIME via `mimetypes` (`.js`/`.mjs` → `text/javascript`, `.svg`, `.webmanifest`). |
| `GET /static/{path}` | **public** (StaticFiles mount of `virtubooth/static`) | serves core SDK, CSS, gate/404 assets. 404 → gate or notfound HTML |
| `GET /admin` | public | **303** → `/admin/live` |
| `GET /admin/login` | public | `admin/static/login.html` |
| `GET /admin/assets/{rel}` | **public** | `admin/static/assets/*` via `safe_file` |
| `GET /admin/{page}` | admin | No session → **303** `/admin/login?next=<quote("/admin/{page}" + ("?"+query if any), safe="/")>`, so `?` and `=` become `%3F`/`%3D`, e.g. `next=/admin/user%3Fid%3D5`. With a session: `page` must be alphanumeric plus `-`, then `admin/static/{page}.html` (live, manage, user) or notfound 404. |
| any other path | — | gate 404 (no access) or notfound 404 (access) |

**Client-side `next`.** `login.js safeNext` accepts only `^\/admin\/[a-z0-9-]*(\?id=\d{1,9})?$`, and never `/admin/` or `/admin/login`. Anything else falls back to `/admin/live`.

### 2.4 Guest API

| Route | Auth | Request | Success | Errors |
|---|---|---|---|---|
| `POST /api/identify` | access + CSRF | body (see below) | (see below) | 404 `scan_qr`; 422; 403 `bad_origin`; 429 budget |
| `POST /api/join` | access + CSRF | body (see below) | (see below) | (see below) |
| `PATCH /api/me` | guest + CSRF | `{instagram?: string≤100 \| null}`; null or blank clears | 200 `{user: GuestUser}`. **Paused guests are allowed.** | 400 `invalid_instagram`; 401 `needs_consent`; 403 `banned`; 404 `scan_qr`; 422 |
| `GET /api/extensions` | access | — | `{party_name, instagram_account, extensions: PublicExtension[]}` (only `show_on_home`, in configured order) | 404 `scan_qr` |
| `POST /api/x/{ext_id}/upload` | guest + CSRF | raw JPEG body; see §2.5 | 201 | see §2.5 |
| `GET /api/x/beer/stats` | **access only** (no consent needed) | — | `{total: number, goal: 1000000}`; `total` = visible, non-deleted beer photos | 404 `scan_qr` |
| `GET /media/{public_id}?thumb=<bool>&download=<bool>` | admin session, **or** access + `vb_uid` user == owner | — | `image/jpeg`, `Cache-Control: private, max-age=86400`; `download` adds `Content-Disposition: attachment; filename="{ext}-{seq:05d}.jpg"`. Hidden photos are still served to the owner; a banned owner still gets their own photos. | 404 `{"error":"not_found","message":"Nicht gefunden."}` (bad id format, unknown, deleted, not owner, file missing); 422 for an unparsable bool |

**`POST /api/identify`**
- Request `{fp?: {hash: FpHash, components?: object}, uid?: string≤256}`:
  - `components` keeps at most 32 keys, each key cut to 32 characters; values that are not bool, number or null become `str[:200]`.
  - `uid` is the localStorage copy of `uid_token`.
- Unknown device: 200 `{state:"needs_consent", consent: ConsentInfo}`, no cookie.
- Known device (by cookie, or by `uid` when the cookie is gone): 200 `{state:"ok"|"banned", user: GuestUser, uploads_stopped: boolean, uid_token: string}` plus `Set-Cookie vb_uid`.
- Side effect: `touch_user` updates `last_seen_at`, `last_ip` and `user_agent[:300]`; with `fp` it also updates `fp_hash`/`fp_components` and upserts `user_fingerprints`.

**`POST /api/join`**
- Request `{accept: true (literal), version: string≤32, instagram?: string≤100|null, fp: Fingerprint (required)}`. Steps, in order:
  1. A cookie user already exists → **200** `{state, user, uploads_stopped, uid_token, already_joined: true, instagram_kept: boolean}`. The handle is set only if the user had none and is not banned. A differing handle is kept out and reported as `instagram_kept: true`.
  2. `version` ≠ `VB_CONSENT_VERSION` → **409** `consent_outdated` "Die Hinweise wurden gerade aktualisiert. Bitte neu laden."
  3. Invalid handle → **400** `invalid_instagram`, with a specific message.
  4. The `new_user_ip` bucket (120 per 10 min per IP) is exhausted → **429** `rate_limited` plus `Retry-After`.
  5. Otherwise the user is created. A banned fingerprint means it starts banned with reason "Gerät gesperrt (Fingerprint)". An active new-guest lock means it starts with uploads paused (`new_guest_lock`, period).
  6. Response **201** `{state:"ok"|"banned", user, uploads_stopped, uid_token, already_joined: false}` plus the cookie.
- Event: `user.created`.
- Errors: 422 (`accept` false, missing or invalid `fp`), 403 `bad_origin`, 404 `scan_qr`.
- `normalize_instagram`: strips spaces and `@`, lower-cases, and accepts an `instagram.com/<handle>` link. The result must match `^[a-z0-9._]{1,30}$` with no `..`. Messages:
  - "Instagram-Namen haben höchstens 30 Zeichen, deiner hat N."
  - "…keine Umlaute und kein ß. Schau nochmal, wie deiner genau geschrieben wird."
  - "…keine Akzente (é, ñ, …), nur die Buchstaben a bis z."
  - "…keine Leerzeichen."
  - "Zwei Punkte hintereinander gibt es in Instagram-Namen nicht."
  - "In Instagram-Namen gehen nur Buchstaben (a bis z), Zahlen, Punkt und Unterstrich."

### 2.5 Upload pipeline (`POST /api/x/{ext_id}/upload`), in check order

| # | Check | Error |
|---|---|---|
| 0 | middleware: CSRF, API budget (no JSON body cap) | 403 `bad_origin`, 429 |
| 1 | `require_guest` | 404 `scan_qr` / 401 `needs_consent` / 403 `banned` |
| 2 | extension exists and has an `UploadPolicy` | 404 `not_found` "Nicht gefunden." |
| 3 | `user.uploads_paused` | 403 `uploads_paused` "Uploads sind für dich gerade pausiert. Die Gastgeber schalten sie bald wieder frei." |
| 4 | stop switch on | 403 `uploads_stopped` "Uploads sind gerade kurz gestoppt – gleich geht's weiter." |
| 5 | `Content-Type` (before `;`) == `image/jpeg` | 415 `unsupported_type` "Nur JPEG-Bilder sind erlaubt." |
| 6 | `upload_user` bucket `user:<id>`, 10/min, **charged on every attempt from here** | 429 `rate_limited` + `Retry-After` |
| 7 | `upload_ip` (IP, 180/min) and `upload_global` ("global", 300/min): **checked only** | 429 + `Retry-After` |
| 8 | declared `Content-Length` > `max_bytes` (policy or `VB_MAX_UPLOAD_BYTES`, 8,000,000) | 413 `too_large` "Das Bild ist zu groß." |
| 9 | `X-VB-Meta` header: `encodeURIComponent(JSON.stringify(obj))`, at most 2048 raw characters; must be a JSON object; keys ⊆ `meta_keys`; values `str≤100` / number / bool / null; then `validate_meta` (a `ValueError` message becomes the response message) | 400 `invalid_meta`: "Metadaten zu lang." / "Metadaten unlesbar." / "Unbekannte Metadaten: ['k']" / "Metadaten-Wert zu lang: k" / "Ungültiger Metadaten-Wert: k" / the extension's message |
| 10 | body streamed with a cap | 413 `too_large`; empty → 400 `empty_upload` "Der Upload war leer." |
| 11 | `process_jpeg` (thread pool): magic `FF D8 FF`, PIL format JPEG, `max(w,h) ≤ max_side`, `min(w,h) ≥ min_side`, `exact_size`; decode; EXIF transpose; RGB; re-encode at `quality` with optimize; thumbnail `thumb_side` at q78 | 400 `invalid_image`: "Nur JPEG-Bilder sind erlaubt." / "Bild ist zu groß (max. N px pro Seite)." / "Bild ist zu klein." / "Bild muss genau 1080×1440 px groß sein." / "Das Bild konnte nicht gelesen werden." |
| 12 | `upload_ip` and `upload_global` **charged** | 429 |
| 13 | write `data/<ext>/<YYYYmmdd-HHMMSS-mmm>_<6hex>.jpg` and `thumbs/…` atomically (`.name.tmp` → `os.replace`); the timestamp uses `VB_TIMEZONE`; insert the row with `seq = max(seq)+1` per extension (never reused); on failure, unlink both files | 500 |
| 14 | `on_upload(ctx)` (thread pool), merged into the response; publish `photo.created {photo: AdminPhoto}` | — |
| → | **201** `{photo: GuestPhoto, ...extra}` | |

**Extension policies** (defaults: `max_side 2400`, `min_side 64`, `quality 85`, `thumb_side 400`, `max_bytes None`):

| Extension | Policy | Meta (`meta_keys` → stored) | `on_upload` extras | Router | Listing |
|---|---|---|---|---|---|
| **beer** | `max_side 1440`, `min_side 480`, `exact_size (1080,1440)`, `quality 85` | `vessel` **required** ∈ {`bottle`,`cup`} ("Unbekanntes Gefäß. Flasche oder Becher?"); `facing` optional ∈ {`user`,`environment`} ("Unbekannte Kamera."), `null` dropped. Stored `{vessel[, facing]}`. A missing header fails (vessel is required). | `{beer_number: seq, total: visible beer count}` | `GET /stats` (access) | order 10, "Beer Cam", 🍺, "Knips dein Bier – auf zur Million!", `meta_labels {vessel:"Gefäß", facing:"Kamera"}` |
| **booth** | `max_side 1440`, `min_side 480`, `exact_size (1080,1440)`, `quality 88` | `filter` **required** ∈ `filters.json` ids ("Unbekannter Filter."); `facing` **required** ∈ {`user`,`environment`} ("Unbekannte Kamera."). Stored `{filter, facing}`. | `{booth_number: seq}` | none (`/api/x/booth/stats` → 404 `http_404`) | order 20, "Fotobox", 📸, "Filter drauf, lächeln, klick! 🤳", `meta_labels {filter:"Filter", facing:"Kamera"}` |

**`filters.json` ids, in strip order:** `normal` (Normal ✨), `bw` (Schwarz-Weiß 🖤), `sepia` (Sepia 📜), `colorpop` (Color Pop 🌹), `party` (Party-Rahmen 🎉), `emoji` (Emoji-Props 🥳), `neon` (Neon 💜), `vhs` (Vintage/VHS 📼), `retro` (Retro-Pixel 👾), `comic` (Comic 💥).
- Each id must match `^[a-z][a-z0-9-]{0,31}$`; ids are unique; names are non-blank.
- The backend loads the file at import time from `extensions/booth/static/filters.json`.

**Extension contract validation:**
- id: `^[a-z][a-z0-9-]{1,30}$`.
- Meta keys: `^[a-z][a-z0-9_]{0,31}$`.
- `static_dir/index.html` must exist.
- `max(exact_size) ≤ max_side`.

### 2.6 Admin auth (`/api/admin`, no `require_admin`)

| Route | Request | Success | Errors and notes |
|---|---|---|---|
| `POST /login` (CSRF) | `{password: string≤256}` | 200 `{"ok": true}` + `vb_admin` cookie; audit `admin.login` (actor `admin:<hash8>`, target `ip:<ip>`) | First `login_ip` (5/60 s) and `login_ip_hourly` (20/h) per IP are **hit on every attempt, successful ones too** → 429 `rate_limited` + `Retry-After`. Wrong password → audit `admin.login_failed` (actor `anonymous`); the global failure bucket (50/h) is hit; when it is exhausted → **429 `login_locked`** "Zu viele Fehlversuche. Login ist kurz gesperrt." (**no Retry-After**); otherwise **401 `wrong_password`** "Falsches Passwort." The correct password is never refused by the global bucket. Also subject to the middleware API budget. |
| `POST /logout` (CSRF) | none (Content-Length 0 is fine) | 200 `{"ok": true}`; deletes the session if one exists; audit `admin.logout`; clears the cookie | — |
| `GET /session` | — | `{"authenticated": boolean}` | — |

### 2.7 Admin API (`/api/admin`, every route requires admin; mutations also need CSRF; all exempt from the API budget)

Route table, 22 routes, pinned by `test_route_table_is_covered`:

| # | Method and path | Request | Success | Errors | Events |
|---|---|---|---|---|---|
| 1 | `GET /photos` | (see below) | `{photos: AdminPhoto[], next: PublicPhotoId \| null, total?: number}` | (see below) | — |
| 2 | `GET /photos/{photo_id}` | path regex | `{photo: AdminPhoto}` | 404 `not_found` "Foto nicht gefunden."; 422 | — |
| 3 | `POST /photos/{id}/hide` | — | `{photo: AdminPhoto, changed: boolean}`; sets `hidden_reason 'admin'`; idempotent | 404, 422 | `photo.hidden {photo}` if changed |
| 4 | `POST /photos/{id}/unhide` | — | `{photo, changed}`; **also clears ban-hidden photos** (`hidden_reason 'ban'`) | 404, 422 | `photo.unhidden {photo}` if changed |
| 5 | `DELETE /photos/{id}` | — | `{ok: true, id}`; the row becomes a tombstone (`deleted_at`), files are unlinked, `seq` is never reused | 404 (unknown or already deleted) | `photo.deleted {id, photo: AdminPhoto(deleted=true) \| null}` |
| 6 | `POST /photos/bulk` | `{ids: PublicPhotoId[] (1..200), action: 'hide'\|'unhide'\|'delete'}` | `{action, changed: id[], unchanged: id[], missing: id[]}` (de-duplicated, order kept) | 422 | one event per changed photo, as in 3–5 |
| 7 | `GET /users` | (see below) | `{users: AdminUserView[], next_offset: number \| null}` | (see below) | — |
| 8 | `GET /users/{user_id}` | `user_id` int in 1..2⁶²−1 | (see below) | 404 "Gast nicht gefunden."; 422 | — |
| 9 | `POST /users/{id}/ban` | `{reason?: string≤200 = "", fingerprint?: boolean = false}`; whitespace in `reason` is collapsed | `{user: AdminUserView, changed, fingerprint_banned: boolean, photos: AdminPhoto[]}`. A ban hides every visible photo with `hidden_reason 'ban'`. | 400 `no_fingerprint` "Für diesen Gast ist kein Fingerprint bekannt." (checked first, nothing done); 404; 422 | `fingerprint.banned {fp_hash, user_id}` if new; `user.banned {user: AdminUserView, photos}` if changed |
| 10 | `POST /users/{id}/unban` | optional `{fingerprint?: boolean}` | (see below) | 404, 422 | (see below) |
| 11 | `GET /device-bans` | — | `{bans: [{fp_hash, created_at, reason, source_user_id: number\|null, source_user_name: string\|null, users: UserRef[]}]}` (newest first) | — | — |
| 12 | `DELETE /device-bans/{fp_hash}` | path `^[0-9a-f]{16,64}$` | `{ok: true, fp_hash, users_unbanned: UserRef[]}`; auto-ban release as in #10 | 404 "Diese Fingerprint-Sperre gibt es nicht."; 422 | `fingerprint.unbanned`, then `user.unbanned` per released user |
| 13 | `GET /stats` | — | `{photos, visible, hidden, deleted, last_upload_at: ISO\|null, guests, banned, instagram /* guests with a handle */, instagram_handles /* distinct */, uploaders, fingerprint_bans, extensions: Record<extId,{photos, hidden}>}` | — | — |
| 14 | `GET /instagram` | — | `{handles: [{handle, users: [{id, name, banned, photos}], photos, visible, hidden, last_upload_at: ISO\|null, recent: AdminPhoto[≤8, visible, newest first]}]}`, sorted by `-photos`, then `handle` | — | — |
| 15 | `GET /audit` | `before?: int (1..2⁶²−1)`, `limit 1..500 (100)` | `{entries: [{id, at, actor, action, target, details: object}], next: number\|null}` (id desc) | 422 | — |
| 16 | `GET /extensions` | — | `{extensions: AdminExtension[]}`; loaded extensions first, then ids that exist only in photos (`title=id`, `emoji 📷`, `tagline ""`, `url null`, `uploads true`, `meta_labels {}`, `loaded false`) | — | — |
| 17 | `GET /events` | — | SSE (§2.8) | 401 JSON | — |
| 18 | `GET /upload-stop` | — | `StopState` | — | — |
| 19 | `POST /upload-stop` | `{enabled: boolean}` | `StopState & {changed}`; audit `uploads.stop` / `uploads.resume` | 422 | `settings.upload_stop {upload_stop: StopState}` if changed |
| 20 | `GET /upload-pause` | — | `PauseState` | — | — |
| 21 | `POST /upload-pause` | (see below) | `PauseState & {changed, restored: number, kept: number}` (counts) | (see below) | (see below) |
| 22 | `POST /users/{id}/uploads` | `{paused: boolean}` | `{user: AdminUser (no auto_* fields), changed}`. Pausing sets source `admin` and clears the lock period; unpausing clears all three columns. Audit `user.uploads_pause`, or `user.uploads_unpause {source}`. | 404, 422 | `user.uploads_changed {users: [AdminUser], paused}` if changed |

**#1 `GET /photos`**
- Query parameters:
  - `extension?: ^[a-z][a-z0-9-]{1,30}$`
  - `hidden?: all|both|""` (both), `1|true|yes|hidden` (hidden only), `0|false|no|visible` (visible only)
  - `user_id?: int string in 1..2⁶²−1`
  - `before?` / `after?`: photo public id (cursor)
  - `limit: 1..200`, default 50
- Ordering is newest first (internal id desc), even with `after`.
- `next` is the last id when `len == limit`, **even if nothing follows**.
- `total` is present only when neither cursor is given.
- Deleted photos are excluded.
- Errors:
  - 400 `invalid_filter`: "Ungültige Aktivität." / "Ungültige Gast-ID." / "Ungültiger Filter für versteckt/sichtbar."
  - 400 `invalid_cursor`: "Unbekannter Cursor." (bad format, or unknown id)
  - 422: limit out of range, or a parameter over its max length

**#7 `GET /users`**
- Query parameters:
  - `search?` (≤100): matches `name LIKE %s%`, `instagram LIKE %s%`, or the exact id (a leading `#` is stripped)
  - `banned?`, `paused?`: `all|both|""|1|true|yes|0|false|no`
  - `limit 1..500` (default 100), `offset 0..1e6`
- Order is id desc. `next_offset = offset+len` when the page is full.
- Errors: 400 `invalid_filter` "Ungültiger Filter."; 422.

**#8 `GET /users/{user_id}`** returns:
- `user`: `AdminUserView`
- `fingerprints`: `[{fp_hash, first_seen, last_seen, shared_with: number, banned: boolean, current: boolean, users: UserRef[]}]`, ordered by `last_seen` desc
- `sharing`: `UserRef[]`
- `photos`: `AdminPhoto[]`, up to 1000, newest first

**#10 `POST /users/{id}/unban`**
- Response: `{user, changed, fingerprints_unbanned: FpHash[], users_unbanned: UserRef[], photos}`.
- Only `'ban'`-hidden photos come back.
- With `fingerprint: true`, every banned fingerprint of this user is lifted. Then the **auto-ban release** runs: it unbans users whose `ban_reason` is the auto reason, who showed one of the lifted hashes, and who show no other banned fingerprint.
- Events: `fingerprint.unbanned {fp_hash}` per lifted hash; `user.unbanned {user, photos}` if changed; then one `user.unbanned` per released user.

**#21 `POST /upload-pause`**
- Request `{enabled: boolean, restore?: boolean}`.
  - `enabled: true` starts a new period (`period = last+1`); idempotent with `changed: false`.
  - `enabled: false` **requires** `restore`, otherwise 400 `restore_required` "Bitte wählen: die pausierten neuen Gäste freischalten oder pausiert lassen."
    - `restore: true` unpauses exactly the users still paused by this period.
    - `restore: false` keeps them paused.
- Audit `uploads.lock_on {period}` / `uploads.lock_off {period, restore, restored, kept}`.
- Errors: 400, 422.
- Events:
  - `settings.upload_pause {upload_pause: PauseState, restored: id[], kept: id[]}` if changed
  - `user.uploads_changed {users: AdminUser[], paused: false}` if anyone was restored

**Audit vocabulary.**
- **actor:** `anonymous` or `admin:<first 8 hex of the session hash>`.
- **target:**
  - `user:<id>`
  - `photo:<public_id>`
  - `fp:<first 16 hex>`
  - `ip:<ip>`
  - `""`
- **actions:**
  - `admin.login`, `admin.logout`, `admin.login_failed`
  - `photo.hide`, `photo.unhide`, `photo.delete`
  - `user.ban {reason}`, `user.unban`
  - `fingerprint.ban {reason}`, `fingerprint.unban`
  - `user.uploads_pause`, `user.uploads_unpause {source}`
  - `uploads.lock_on`, `uploads.lock_off`
  - `uploads.stop`, `uploads.resume`

### 2.8 SSE: `GET /api/admin/events` (the only event stream; there is no guest stream)

**Wire format.**
- First chunk: `retry: 3000\n\n`.
- Each event: `id: <n>\nevent: <type>\ndata: <json>\n\n`. `n` is a process-local counter that resets on restart. `Last-Event-ID` is **not** supported; there is no replay.
- After 15 s idle: `: ping\n\n`.
- `Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`.

**Session.** The stream re-checks the admin session at most every 30 s (`SESSION_RECHECK_SECONDS`, monkeypatched in e2e) while chunks flow. When the session is gone it ends; the client reconnects, gets 401 and goes to login.

**Bus.** Every subscriber has a queue of 256. On overflow the subscriber is dropped (see the bug in §7).

| Event | Published by | Payload |
|---|---|---|
| `photo.created` | upload | `{photo: AdminPhoto}` |
| `photo.hidden` / `photo.unhidden` | hide, unhide, bulk | `{photo: AdminPhoto}` |
| `photo.deleted` | delete, bulk | `{id: PublicPhotoId, photo: AdminPhoto \| null}` (`deleted: true`) |
| `user.created` | join (new) | `{id: number, name: string, banned: boolean, uploads_paused: boolean}` |
| `user.banned` / `user.unbanned` | ban, unban, auto-ban release | `{user: AdminUserView, photos: AdminPhoto[]}` |
| `fingerprint.banned` | ban with fingerprint | `{fp_hash, user_id}` |
| `fingerprint.unbanned` | unban with fingerprint, `DELETE device-bans` | `{fp_hash}` |
| `user.uploads_changed` | per-guest pause, lock end with restore | `{users: AdminUser[] /* no auto_banned */, paused: boolean}` |
| `settings.upload_stop` | stop switch | `{upload_stop: StopState}` |
| `settings.upload_pause` | lock switch | `{upload_pause: PauseState, restored: number[], kept: number[]}` |

The ARCHITECTURE.md and events.py docstrings miss `fingerprint.*`; the list above is complete.

**Client behaviour** (admin.js `connectEvents`, keep it):
- Status values: `connecting` / `live` / `reconnecting` / `polling`.
- While the stream is down, poll every 5 s through a page resync.
- On `readyState CLOSED`: check `/api/admin/session`, then reopen after 4 s.
- On `visibilitychange` to visible: reopen if the stream is not OPEN, otherwise resync.
- Pages connect only after their first fetch, so events in that gap are missed until the next resync.

### 2.9 Error-code catalogue

| Code | Status | Where |
|---|---|---|
| `scan_qr` | 404 | `require_access` routes |
| `needs_consent` | 401 | `require_guest` |
| `banned` | 403 | `require_guest` |
| `uploads_paused`, `uploads_stopped` | 403 | upload |
| `rate_limited` | 429 + `Retry-After` | middleware, join, upload, login |
| `login_locked` | 429 (no `Retry-After`) | login |
| `wrong_password` | 401 | login |
| `admin_required` | 401 | admin |
| `bad_origin` | 403 | middleware |
| `length_required` | 411 | middleware |
| `too_large` | 413 | middleware ("Anfrage zu groß.") or upload ("Das Bild ist zu groß.") |
| `consent_outdated` | 409 | join |
| `invalid_instagram` | 400 | join, me |
| `unsupported_type` | 415 | upload |
| `invalid_meta` | 400 | upload |
| `empty_upload` | 400 | upload |
| `invalid_image` | 400 | upload |
| `not_found` | 404 | upload ext, media, admin |
| `invalid_filter` | 400 | admin lists |
| `invalid_cursor` | 400 | admin photos |
| `no_fingerprint` | 400 | ban |
| `restore_required` | 400 | upload-pause |
| `invalid_request` | 422 | validation |
| `http_<n>` | n | framework |
| `network`, `timeout` | 0 | **client-only**, in vb.js |

---

## 3. Frontend behaviour inventory per screen

Shared by every page:
- Each page links `/static/core/vb.css` and `<script src="/static/core/loader.js" defer>`, plus its own `type="module"` script.
- Each page has `lang="de"`, the meta viewport with `viewport-fit=cover`, `robots noindex`, the `/static/core/icon.svg` icon and `theme-color #14021f` (booth uses `#000`).

### 3.1 SDK basics (vb.js)

**`api()`**
- Sends `Accept: application/json` and `credentials: 'same-origin'`; the `json` option is serialised.
- Throws `ApiError {name:'ApiError', status, code: data.error || 'http_<s>', message: data.message || fallback, data, retryAfter, offline}`.
- On 429/503 with `Retry-After` it sets `retryAfter` and rewrites the message to `"<message without trailing period> (in N s nochmal)."`, or `(in ⌈N/60⌉ min nochmal).` when N ≥ 90.
- `code === 'scan_qr'` triggers `location.reload()`; the server then shows the gate.
- Network failure gives `code 'network'`, status 0. `offline = navigator.onLine === false`. The message is "Keine Verbindung. Bist du noch im Netz?" when offline, otherwise "Keine Antwort vom Server. Prüf dein Netz und versuch es nochmal." because a blocked request and a dead network look alike.

**`uploadJpeg(extId, blob, {meta, onProgress})`**
- XHR `POST /api/x/<ext>/upload` with `Content-Type: image/jpeg` and `X-VB-Meta` (only when meta is non-empty); timeout 60 s; `onProgress(loaded/total)`, then 1.
- Errors go through the same `errorFromResponse`. XHR error gives `network` ("Keine Verbindung. Nochmal versuchen?"); timeout gives `ApiError(0,'timeout','Der Upload hat zu lange gedauert. Nochmal versuchen?')`.
- Every answer feeds `noteUploadAnswer`, which keeps the pause hint in sync.

**`fatal(err, {title, actions})`**
- Returns null for `scan_qr`. Does not stack (reuses `.vb-notice[data-testid=fatal]`).
- `network` + offline: 📡 "Keine Verbindung" / "Dein Handy ist gerade offline. Sobald du wieder Netz hast, lade die Seite neu."
- `network` otherwise: 📡 "Keine Antwort" / "Die Seite erreicht den Server gerade nicht. Prüf dein Netz, und falls du einen Werbe- oder Tracking-Blocker nutzt, schalte ihn für diese Seite aus. Dann lade neu."
- An `ApiError` or `CameraError` with a message shows that message.
- Anything else: 😵 "Ups" / "Da ist etwas schiefgelaufen. Lade die Seite neu." The raw message is never shown.
- The button "Neu laden" (`data-testid=reload`) is focused.

**Feedback helpers.**
- **`showNotice(emoji, title, text, ...actions)`**: a full-screen `.vb-notice[role=alert]` (z 900).
- **`toast(msg, {type: info|success|error, ms=2800})`**: a host `.vb-toast-host[aria-live=polite]`; each toast has `role=alert` for errors, otherwise `status`.
- **`confetti`**: a canvas at DPR ≤ 2 with 140 particles; skipped under `prefers-reduced-motion`.
- **`flash`**: 400 ms. **`vibrate`**: try/catch.
- **`saveImage(blob, name, {preferShare})`**: on iOS (or when asked) uses `navigator.share({files})` when `canShare`. `AbortError` returns `'cancelled'`; any other failure falls back to a download via `<a download>` with an object URL revoked after 30 s.

**Debug panel (`?debug`).**
- `?debug` sets sessionStorage `vb_debug=1`, which persists for the tab.
- `.vb-debug[data-testid=debug]` sits at the top with `pointer-events: none`. It contains `pre.vb-debug-log` and the toggle `button.vb-debug-toggle[data-testid=debug-toggle][aria-expanded]` 🐞. The folded state is kept in sessionStorage `vb_debug_folded`.
- It logs `window` errors and unhandled rejections.

**`h(tag, attrs, ...children)`**: `on*` functions become listeners; `class`, `dataset` and boolean attributes are supported; text children become text nodes. **innerHTML is forbidden** (tested).

### 3.2 Join dialog (`boot()` → `askConsent`)

**Flow.**
1. `getFingerprint()`, then `POST /api/identify {fp, uid: localStorage.vb_uid}`.
2. `needs_consent` shows the dialog.
3. Afterwards: store `uid_token` to `localStorage['vb_uid']`, set `uploadsStopped`, `setUser`.
4. If banned and `showBannedNotice` (the default), show the notice 🚫 "Gesperrt" / "Dieses Gerät wurde für Uploads gesperrt. Sprich die Gastgeber an, wenn das ein Versehen ist."
5. Returns `{user, banned}`.

**DOM.**
- `.vb-scrim[data-testid=join]`
  - `> .vb-sheet.vb-sheet--split[role=dialog][aria-modal=true][aria-labelledby=vb-join-title][tabindex=-1]`
    - `> form.vb-sheet-form`
      - `> .vb-sheet-body`:
        - `h2#vb-join-title` (`consent.title`)
        - `p.vb-muted` × 3 paragraphs
        - `label[for=vb-join-insta]` (`instagram_prompt`)
        - `input#vb-join-insta.vb-input[type=text][inputmode=text][autocomplete=off][autocapitalize=none][spellcheck=false][placeholder=@deinname][maxlength=31]`
        - `div.vb-field-error[role=alert]`
      - `+ .vb-sheet-foot > .vb-actions > button.vb-btn.vb-btn--primary.vb-btn--big[type=submit]` (`accept_label`)

**Behaviour.**
- **There is no way out:** Escape and a scrim tap do nothing, because declining means not using the site.
- Initial focus is on **the dialog, not the field**, so the phone keyboard does not cover the text.
- Custom Tab / Shift+Tab cycling, because "Safari skips buttons". A `focusin` guard pulls focus back inside.
- `.vb-sheet--more` is toggled while the body can still scroll (ResizeObserver plus scroll). It shows a fade and a border above the footer.
- **Pasting** text containing `instagram.com/<h>` replaces the field with `@<h>`.
- **Submit:**
  1. Disable the button; `POST /api/join {accept:true, version, instagram: trimmed||null, fp}`.
  2. Success: close.
     - `already_joined`: toast `Du bist schon dabei als „<name without #N>“ (@insta)?. [Tipp auf deinen Namen, um Instagram zu ändern.]` for 6000 ms; the hint is added when `instagram_kept`.
     - Otherwise, when the state is `ok`: confetti.
  3. Error: the message goes in `.vb-field-error`, scrolled into view, and the button is re-enabled. For `invalid_instagram`, focus the field. For `consent_outdated`, reload after 1500 ms.
- Small phones (down to 320×460) must keep the button on screen (§6).

### 3.3 User chip and Instagram editor

**Chip.**
- `button.vb-chip[data-testid=user-chip]` containing `span.vb-chip-icon` 🙂 and `span.vb-chip-text`.
- Text: `@handle`, otherwise `<pseudonym without " #N"> · Insta?`.
- `title` = `<name>[ · @handle]`. Hidden without a user. Long text ellipsises.
- Click opens `editInstagram()`. That is a no-op without a user or while a `.vb-scrim` is open.

**Editor dialog.**
- `.vb-scrim[data-testid=handle-edit]` with a split sheet:
  - `h2#vb-insta-title` "Dein Instagram"
  - text `Du bist hier „<name>“. Wenn du magst, markieren wir dich auf Instagram.`
  - label "Instagram-Name (freiwillig)"
  - `input#vb-insta-edit`, pre-filled with `@handle`, `maxlength 31`, with the same paste rule
  - buttons "Speichern" (submit) and "Abbrechen"
- Dismissed by Escape, a scrim click or Abbrechen. Focus starts on the input and returns to the chip on close.
- Submit: `PATCH /api/me` → `setUser` → close → toast "Gespeichert ✨" (success).
- Errors are shown in the field and the input is re-focused. A banned device gets the 403 `banned` text here.

### 3.4 Upload pause/stop hint (in vb.js, on every guest page)

**State.**
- `paused` when `user.uploads_paused && !user.banned`.
- Otherwise `stopped` when `uploads_stopped`.
- Banned devices get no hint.

**DOM.**
- `button.vb-pausechip[data-testid=uploads-paused][data-kind=paused|stopped]`.
- Text: "⏸ Uploads sind gerade pausiert" or "⏹ Uploads kurz gestoppt".
- Placed inside `#vb-uploads-slot` if the page has one (home does; inline variant), otherwise fixed at `top: 68px + safe-top` (z 950).

**Click** opens `.vb-scrim[data-testid=uploads-paused-info]` with:
- title "⏸ Uploads sind für dich pausiert" / "⏹ Uploads sind kurz gestoppt"
- text:
  - paused: "Die Gastgeber haben Uploads für dich kurz angehalten. Du kannst dich weiter umsehen und deinen Instagram-Namen ändern. Sobald sie wieder freigeben, verschwindet dieser Hinweis."
  - stopped: "Die Gastgeber haben Uploads gerade für alle angehalten. Gleich geht's weiter – dann verschwindet dieser Hinweis von selbst."
- button "Alles klar", focused
- Escape or a scrim click closes it. There is no focus trap.

**Recheck.**
- While the hint shows: `POST /api/identify {uid}` every 30 s (only while visible), and on `visibilitychange` to visible.
- When the hint clears: toast "Uploads sind wieder frei 🎉".
- Upload answers update the state immediately: `ok` clears both, `uploads_paused` sets paused, `uploads_stopped` sets stopped and clears paused.

### 3.5 Home (`/`)

**DOM.**
- `main.vb-page`
  - `header.home-header`: `#user-chip`, `#vb-uploads-slot`, `h1 > span.vb-grad-text#party-name` + " 🎉", `p` "Such dir was aus:"
  - `nav#tiles.home-tiles[aria-label=Aktivitäten]`
- CSS: `#party-name:empty::before` shows "…".

**Flow.**
1. Start `GET /api/extensions` **before** `boot()`, so the party name and `document.title` show behind the join dialog.
2. `boot()`, then `mountUserChip`.
3. Tiles: `a.home-tile[href=/x/<id>/][data-testid=tile-<id>]` containing the emoji span (`aria-hidden`), `.home-tile-title` and `.home-tile-tagline`. Colours cycle 3n+1/2/3.
4. With none: "Noch nichts freigeschaltet."
5. Any failure goes to `fatal`. The e2e tests cover identify blocked, offline, and 429 with `Retry-After: 12` (exact message).
- Desktop: tiles in one centred column (≤560 px); Enter on a focused tile navigates.

### 3.6 Gate, 404 and the loader hint

**Gate (`gate.html`, HTTP 404, no JS).**
- `main.vb-page.vb-center[data-testid=gate]`: 📷 (`.vb-notice-emoji`, ≥60 px); `h1 > .vb-grad-text` "Scan den QR-Code!"
- "So geht das leider nicht. Diese Seite funktioniert nur, wenn du einen der QR-Codes auf der Party scannst."
- muted "Halte einfach die Kamera deines Handys auf den Code und tippe auf den Link."

**404 (`notfound.html`).**
- `[data-testid=notfound]`: 🤷, "Hier ist nichts.", "Die Seite gibt es nicht. Zurück zur Party?", `a.vb-btn--primary[href=/]` "Zur Startseite".

**Loader (`loader.js`, a classic deferred script).**
- After 6000 ms without `window.__vbReady`: `.vb-notice[role=alert][data-testid=load-failed]` with 🧩, "Die Seite startet nicht", "Wahrscheinlich blockiert ein Werbe- oder Tracking-Blocker einen Teil der Seite. Schalte ihn für diese Seite aus und lade neu." and the button "Neu laden".
- It must remain a non-module, non-bundled script that does not depend on the app bundle.

### 3.7 Beer Cam (`/x/beer/`)

**DOM (static in index.html; tests depend on the ids and test ids).**
- `main.beer-app#app[data-state][data-vessel][data-testid=beer-app]`.
- Header:
  - back `a.vb-icon-btn[href=/][aria-label="Zurück zur Startseite"][data-testid=back]`
  - `#user-chip`
  - counter `[data-testid=counter][title="Biere bisher"]`: 🍺 `b#count` "…", `#goal-long` "/ 1.000.000", `#goal-short` "/ 1 Mio."
- In-app hint `p#inapp[data-testid=inapp-hint][hidden]`: "Kamera geht nicht? Öffne den Link in Safari oder Chrome (⋯ › „Im Browser öffnen“)." with close ✕ `#inapp-close`.
- `section.beer-viewport > .beer-frame#frame[data-testid=frame]` containing:
  - `video#video[playsinline muted autoplay]`
  - the loading overlay `#loading` (spinner, "Kamera startet…")
  - the upload panel `#upload[data-testid=upload][hidden]`: `#upload-text[aria-live=polite]`, `.vb-progress[data-testid=upload-progress] > #upload-bar`, actions `#upload-actions` with `#retry[data-testid=retry]` "Nochmal", `a#upload-home[data-testid=upload-home][hidden]` "Zur Startseite", `#discard[data-testid=discard]` "Verwerfen"
  - the hint `p#hint[data-testid=hint]`
- Footer:
  - `.beer-vessels[role=radiogroup][aria-label=Gefäß]` with `button.beer-vessel[role=radio][aria-checked][data-vessel=bottle|cup][data-testid=vessel-bottle|vessel-cup]` (an icon SVG is prepended)
  - shutter `#shutter.vb-shutter[aria-label="Foto aufnehmen"][data-testid=shutter][disabled]`
  - `#switch[data-testid=switch-camera][aria-label="Kamera wechseln"][disabled]`
- Success `section#success[data-testid=success][aria-live=assertive][hidden]`:
  - polaroid `img#success-img` (1080×1440) with caption `#success-caption`
  - `h1[data-testid=success-title]` "Bier `#success-num` geloggt 🍺"
  - `#success-cheer`
  - `[data-testid=success-count]` 🍺 `#success-total` `/ goal`
  - `#success-togo[data-testid=success-togo]`
  - `#again[data-testid=again]` "Noch eins! 🍺", `a[data-testid=home]` "Zur Startseite"
- The overlay SVG: `svg.beer-overlay[viewBox 0 0 1080 1440][preserveAspectRatio=none][data-testid=overlay][data-vessel]` with groups `.beer-guide--bottle|cup[data-testid=overlay-<v>]`. Each group has paths `.beer-guide-shade` (even-odd darkening), `-halo`, `-detail`, `-shine` and `-line`, using `vector-effect: non-scaling-stroke`.

**States (`data-state`).**
- `loading` and `camera`. Shutter and switch are enabled only in `camera` with a camera.
- `uploading`, `error`, `success`, `off`.
- Switch is hidden when `!cam.canSwitch`.

**Flow.**
1. `wireUi`; vessel from `localStorage.vb_beer_vessel` (default bottle); in-app hint (`isInAppBrowser()` and not `localStorage.vb_beer_inapp_dismissed`).
2. `boot({showBannedNotice:false})` → `mountUserChip` → `refreshStats`.
3. If banned, show the banned notice (stop the camera; 🚫 "Gesperrt" + `BANNED_TEXT` + primary link "Zur Startseite"; `data-testid=banned`). Otherwise `startCamera` with `facing 'environment'`, 1920×1440 (4:3).

**Shoot.**
1. Guard: not busy, state `camera`.
2. `flash`, `vibrate(40)`; if `!cam.live`, restart.
3. `captureFrame(video, 1080, 1440, {mirror: cam.mirrored})`; the canvas `.beer-still[data-testid=still]` is inserted under the overlay to freeze the frame.
4. JPEG 0.9; `pending = {blob, canvas, meta:{vessel, facing: cam.facing}}`; upload with progress: "Wird geloggt… N %", then "Fast geschafft…".

**Upload failures.**

| Code | Behaviour |
|---|---|
| `banned` | discard, banned notice |
| `uploads_paused` | `pending=null`; state `error`; server message; retry hidden; "Zur Startseite" shown |
| `needs_consent` | `boot()` again (join dialog), then the normal error UI with retry |
| `rate_limited` | text "Langsam! Zu viele Fotos auf einmal. In N s nochmal." (or "… Warte kurz und versuch es nochmal."); the retry button counts down "⏳ N s", disabled, then "Nochmal" |
| anything else | the server or network message |

The error state also shows a 5 s error toast.

**Discard** removes the stills and returns to `camera`.

**Success.**
- **The number shown is the board count** (`res.total`, which excludes hidden and deleted beers), not `seq`. Both the title and the counter use it.
- Caption `Bier #N · Flasche|Becher`. To-go text: `Noch X bis zur Million – weiter so!` or "Die Million ist voll! Ihr seid Legenden. 🏆".
- Every 100th: "Jubiläumsbier! 🎉 #N" with confetti `{count:260, duration:3200}`; otherwise a random cheer from 7 and normal confetti.
- `vibrate([30,60,30])`; focus "Noch eins!".
- **Again:** hide, remove stills, revoke the URL; restart the camera if not live (or show a notice); state `camera`; focus the shutter; `refreshStats`.

**Stats.**
- `GET /api/x/beer/stats` every 30 s while visible.
- An upload "epoch" guard ignores stale polls.
- `de-DE` number formatting; the counter "bump" animation restarts on change. The short goal uses `Intl` compact notation ("1 Mio."), for phone width.

**Keyboard.**
- Space or Enter shoots when state is `camera`, `document.activeElement === body`, no modifiers, no `.vb-scrim`/`.vb-notice`, and the user is not typing.
- Escape on success runs "again".

**Other behaviour.**
- `beforeunload` is blocked while `pending` exists (uploading or failed).
- **Camera errors:** notice 📷 "Kamera geht nicht" + `err.message` + "Neu laden" + "Zur Startseite".
- **Switch failure:** toast, revert to the previous facing and restart, or show the notice.
- **Boot failure** (local `fatal`): state `off`; 😵 "Ups" + `ApiError` message or "Die Beer Cam konnte nicht starten." + "Neu laden" + "Zur Startseite".

**Layout (beer.css).**
- `.beer-viewport` has `container-type: size`.
- `.beer-frame { width: min(100cqw, (100cqh - hintH)*0.75); aspect-ratio: 3/4 }`, with an `@supports not (1cqw)` fallback.
- Video and still use `object-fit: cover`, centred. `.is-mirrored { transform: scaleX(-1) }`.
- `@media (orientation: landscape) and (max-height: 600px)`: a grid with the box left at full height and everything else on the right; the success screen side by side with no scrolling.
- Further breakpoints at max-height 640/720 and max-width 350/430.

### 3.8 Fotobox (`/x/booth/`)

**DOM.**
- `div.booth#booth[data-testid=booth]` with `data-screen=camera|result`, `data-ready=1`, `data-renderer=webgl|canvas2d`, `data-filter=<id>`, `data-facing`, `data-mirror=1|0` and `data-counting=1`.
- Top bar:
  - back `a#back[href=/][data-testid=back]` "←" (`aria-label` "Zurück zur Übersicht")
  - title "📸 Fotobox"
  - `#user-chip`
  - the outbox chip `button#outbox.vb-chip.booth-outbox.vb-hidden[data-testid=outbox]`
- Preview `.booth-frame#frame[data-testid=preview]` containing:
  - `video#video` (opacity 0.001; iOS needs it on the page)
  - `#canvas-slot` → `canvas.booth-canvas[data-testid=preview-canvas]`
  - `#filter-name[aria-live=polite][data-testid=filter-name]`
  - `#countdown[aria-live=assertive][data-testid=countdown]`
  - `#loading` "Kamera startet …"
- Strip `#strip[role=listbox][aria-label=Filter][data-testid=filter-strip]` (gets `.is-fit` when everything fits) with chips `button.booth-chip[role=option][aria-selected][data-filter][data-testid=filter-<id>]` (icon + name).
- Controls:
  - `#countdown-toggle[aria-pressed][aria-label="Countdown 3-2-1"][data-testid=countdown-toggle]` "⏱️ 3s"
  - `#shutter[aria-label="Foto machen"][data-testid=shutter]`
  - `#switch-camera[data-testid=switch-camera]` 🔄
- Result `section#result.vb-hidden[data-testid=result][aria-label="Dein Foto"]`:
  - `#result-title` (random from 6)
  - `img#result-photo[data-testid=result-photo]` (a `blob:` URL)
  - `#upload[data-testid=upload-status][data-state=idle|uploading|done|error]` with `#upload-text`, `#upload-progress > #upload-bar`, `#upload-retry[data-testid=upload-retry]` "↻ Nochmal hochladen", `a#upload-home[data-testid=upload-home]` "Zur Startseite"
  - `#save[data-testid=save]` "⬇️ Speichern" (`#save-label`)
  - `#again[data-testid=again]` "📸 Nochmal"

**Boot.**
1. `updateButtons`; `beforeunload` guard; back-link guard.
2. `boot({showBannedNotice:false})` → chip. If banned: banned notice.
3. `resumeOutbox()`.
4. `Promise.all([api('./filters.json'), api('/api/extensions').catch(null)])`; title `Fotobox · <party>`; `overlayInfo = {partyName, title: "<party> 🎉", date}`.
5. One shared 1080×1440 overlay canvas. `setupRenderer(?renderer=` query; `canvas2d` forces the fallback).
6. `buildFilterList`, `buildStrip`, `bindControls`, `selectFilter(0)`; camera with `facing 'user'`, 1440×1080.
7. Boot failures: 😵 "Ups" + `ApiError` message or "Die Fotobox konnte nicht starten." + "Neu laden" + "Zur Startseite".

**Render loop.**
- rAF loop, only when a camera exists, the page is visible and no result is shown.
- Every 1 s, call `video.play()` if the video is paused (iOS).
- The first drawn frame sets `data-ready=1` and enables the buttons.
- Wake Lock `screen` is requested on loop start.
- `visibilitychange`: stop when hidden, start when visible.
- Canvas backing store = frame width × DPR (≤2), capped at 1080 (WebGL) or 480 (Canvas2D); the height follows from 3:4. A ResizeObserver on the frame and the strip handles resizes.

**Filters.**
- `selectFilter(i)` wraps around and compiles the shader at `setFilter`. On failure: toast "Dieser Filter klappt auf deinem Handy leider nicht." and the previous filter's overlay is redrawn.
- `aria-selected`, smooth centring of the chip, and an announced name `<icon> <name>` (fresh node, so the animation restarts).
- `fitStrip`: adds `is-fit` when the total chip width + 32 ≤ the strip width.
- **Gestures on the preview** (pointer events): a horizontal swipe (|dx| > 40 and > 1.3·|dy|) goes to the next or previous filter with `vibrate(8)`. A tap (<12 px) followed by a second within 320 ms is a double tap, which switches the camera.

**Countdown.**
- The toggle persists `localStorage.vb_booth_countdown` ('1'/'0') and shows a toast "Countdown an: 3 … 2 … 1 ⏱️" / "Countdown aus" (1400 ms).
- The countdown shows 3, 2, 1 at 1 s each with `vibrate(12)`.

**Shoot.**
1. Optional countdown.
2. **`stopLoop()` freezes the preview, so the frame on screen is the photo.**
3. `flash`, `vibrate(40)`, `renderer.capture()`, `canvasToJpeg(0.9)`.
4. Result screen: random title; Save focused; background upload with `meta {filter, facing}`.
5. Error: toast "Das Foto hat nicht geklappt. Nochmal?" and the loop restarts.

**Shot lifecycle.**
- A shot is `{id, blob, meta, status idle|uploading|done|error, progress, seq, error, waitUntil, attached, stored, resumed, banned, paused}`.
- `state.unsent` holds every shot not yet on the server.

| Outcome | Behaviour |
|---|---|
| **done** | "Hochgeladen ✓ · Foto #<seq>". Attached: confetti(90). Resumed: toast `Foto #N von vorhin ist jetzt hochgeladen ✓` (4 s). Background: `Foto #N ist hochgeladen ✓`. Then removed from the outbox and IndexedDB. |
| **banned** | `state.banned`; the IndexedDB copy is kept; result shows "Nicht hochgeladen: …"; retry and again hidden; home shown; the banned notice appears once back on the camera. |
| **uploads_paused** | IndexedDB copy kept; no retry; home shown; for background shots a toast at most every 5 s. |
| **rate_limited** | the same countdown pattern as Beer Cam ("↻ Nochmal in N s"). |
| **permanent 4xx** (not 401/408/429) | settled (dropped from the outbox); a background toast `Ein Foto lässt sich nicht hochladen: …`. |
| **transient** (network, 5xx, 401) | the outbox keeps the shot in IndexedDB. `needs_consent` triggers `rejoin()` (`boot` again, join dialog). |

**Outbox.**
- When the guest moves on from a failed shot (Again or Escape), it goes into the outbox chip: "⚠️ N nicht hochgeladen · nochmal", `aria-label` "N Foto(s) nicht hochgeladen. Nochmal hochladen".
- Retried on chip click and on `window 'online'`. The next visit resumes kept records.

**Leaving.**
- `beforeunload` is blocked only while a shot is unsent **and** not stored in IndexedDB.
- The back link with unsent shots opens `.vb-scrim[data-testid=leave]`:
  - title "⚠️ 1 Foto ist noch nicht hochgeladen" / "⚠️ N Fotos sind noch nicht hochgeladen"
  - text "Wenn du jetzt gehst, ist es / sind sie weg." when at risk, otherwise "Es bleibt / Sie bleiben auf deinem Handy und wird / werden hochgeladen, sobald du die Fotobox wieder öffnest."
  - buttons `leave-stay` "Nochmal hochladen" (retries) and `a[data-testid=leave-go]` "Trotzdem gehen"
  - Escape or a scrim click closes it and focuses back. There is no focus trap.

**Save.**
- `saveImage(blob, fotobox-<seq|HHMMSS>.jpg)`; the label becomes "Gespeichert ✓" (`data-saved=1`).
- Error toast "Speichern hat nicht geklappt. Halte das Foto gedrückt und sichere es so."

**Keyboard.**
- Never with modifiers, an open dialog or notice, or while typing.
- On the result screen: Escape goes back to the camera.
- Otherwise, when focus is on body, in the strip, or on the shutter: ArrowLeft/ArrowRight change filter (and keep focus on the selected chip when in the strip). Space or Enter shoot only when focus is on body.

**Camera errors.**
- Notice 📷 "Die Kamera geht nicht" + message, with `.booth-notice-actions`: "Nochmal versuchen" (reload) and "Zur Übersicht".
- Switch failure: toast, restore the previous facing.

**Layout.**
- `.booth-frame { width: min(100cqw, 75cqh); aspect-ratio: 3/4 }`; `touch-action: none` on the preview.
- Landscape (≤600 px high): preview on the left, controls on the right; result side by side with no scrolling.
- At ≤560 px or in landscape the outbox chip gets its own row.

### 3.9 Admin (summary; the full detail is in Appendix A)

- **Login** (`/admin/login`):
  - `#login-form`, `#password[autocomplete=current-password][maxlength=256][autofocus]`, `#login-error[role=alert][data-testid=login-error]`, `#login-submit` "Anmelden".
  - On load, `GET /api/admin/session` redirects if already logged in.
  - Empty field: "Bitte das Passwort eingeben." While submitting: "Prüfe…", then "Willkommen!" → `location.replace(safeNext)`.
  - Errors show the server text, then `input.select()`.
- **Shared chrome:**
  - Sticky header with `#conn[data-testid=conn][data-state]`: "Verbinde…" / "Echtzeit" / "Verbinde neu…" / "Abruf alle 5 s".
  - Navigation links and `#logout` 🚪 "Abmelden" (`POST /api/admin/logout`, then `/admin/login`).
  - `aapi()`: on 401 `admin_required` it calls `goLogin()` once (to `/admin/login?next=<pathname>`; **the query is dropped**, a bug) and returns a never-resolving promise.
  - Toasts via vb.js. Relative times refresh every 30 s (`time[data-rel]`).
  - `describeUA`, `relTime` and `absTime` are pure helpers; port them verbatim.
- **Live** (`/admin/live`): only hide and unhide are allowed. A static test forbids any delete code in live.js.
  - Stats `#stat-photos`, `#stat-guests`, `#stat-hidden`; the uploads chip; the feed `#feed[data-testid=feed][aria-live=polite]` of `article.adm-card[data-testid=photo-card][data-photo-id]`.
  - `#new-pill` "⬆ N neue Fotos" when not at the top. Scroll is compensated (`overflow-anchor: none`).
  - `#empty`; "Ältere Fotos laden" plus infinite scroll (IntersectionObserver, 400 px); pages of 30.
  - Stats on load, throttled at 800 ms after events, and every 60 s.
  - Resync logic: inside the server's window, missing photos count as deleted.
- **Manage** (`/admin/manage`):
  - The uploads chip sits **above** the tabs.
  - ARIA tabs fotos, gaeste, instagram, sperren, protokoll, with roving tabindex, ←/→ wrapping, Home/End and automatic activation; panels have `tabindex=0`.
  - Count badges come from `/stats`.
  - URL state `tab`, `ext`, `status`, `user`, `show=paused` via `history.replaceState`.
  - The tabs:
    - **Fotos:** filters (`<select>`s with aria-labels; segmented status); pages of 48; infinite scroll; Shift-click range selection; a bulkbar to hide, unhide, delete or cancel (chunks of 200); a manage-specific new pill; the lightbox with download, copy handle, toggle and delete.
    - **Gäste:** search debounced at 250 ms; filter Alle/Gesperrte/Nicht gesperrt/⏸ Pausiert; offset paging of 100.
    - **Instagram:** handle rows, copy one or all (banned left out), profile link, "Alle N Fotos von #id" jumps to the Fotos tab filtered by that user.
    - **Sperren:** banned guests and fingerprint bans with one-tap unban, plus auto-ban notes.
    - **Protokoll:** audit table, pages of 100, German action labels.
  - SSE effects use per-tab `invalidate` with throttles.
- **User page** (`/admin/user?id=N`):
  - Profile panel. Nothing is editable.
  - Guest uploads panel: pause or allow.
  - Ban panel: reason field, a fingerprint checkbox with an always-visible warning, a confirm dialog, unban with an optional fingerprint unban and an auto-ban release hint.
  - Uploads grid, fingerprints with sharing peers, device details.
  - Snapshot/restore of typed input and focus across live re-renders; `panelKey` avoids needless rebuilds.
- **Lightbox:**
  - `role=dialog` with `aria-modal` and `inert` on its siblings; it pushes a history entry so the phone Back button closes it.
  - Keys: Escape, ←/→ (newer/older); Tab is trapped.
  - Shows the thumb first, then the full image. It closes if the photo disappears, and focus returns sensibly.
  - There is **no** swipe, image error state, preloading or wrap-around.
- **Confirm dialog:**
  - `role=alertdialog`; capture-phase Escape; trap plus inert. Initial focus is on Cancel for destructive actions.
  - Used only for deleting photos and banning a guest.
- **Uploads chip and sheet:**
  - `[data-testid=uploads-chip]`: "🟢 Uploads laufen" / "⏸ Neue Gäste pausiert seit HH:MM · N betroffen" / "⏹ Alle Uploads gestoppt seit HH:MM[ · ⏸ neue Gäste pausiert]".
  - The sheet has `role=switch` toggles. Ending the pause needs an explicit restore-or-keep choice view.
  - **There is no focus trap, no inert background and no focus return** (bug).

**Storage and timers across all screens.**

| Kind | Keys and values |
|---|---|
| localStorage | `vb_uid` (`uid_token`), `vb_beer_vessel`, `vb_beer_inapp_dismissed`, `vb_booth_countdown` |
| sessionStorage | `vb_debug`, `vb_debug_folded` |
| IndexedDB | `vb-booth` v1, store `outbox`, keyPath `id`, record `{id, meta, at, type, data: Blob \| ArrayBuffer}` |
| history | `history.state.admLightbox` |

Timers: guest pause recheck 30 s; beer stats 30 s; loader 6 s; admin relative times 30 s, live stats 60 s, SSE poll 5 s, SSE retry 4 s.

---

## 4. Camera and rendering specifics (port 1:1)

### 4.1 `camera.js`

**`openCamera(video, {facing='environment', width=1920, height=1080})`**
- Sets the `playsinline` and `autoplay` attributes and `muted`.
- `getUserMedia({audio:false, video:{facingMode:{ideal:facing}, width:{ideal}, height:{ideal}}})`.
- On `OverconstrainedError`, retries **exactly** `{audio:false, video:{facingMode: facing}}` (tested).
- Without `mediaDevices`: `CameraError('unsupported', …)` with the in-app hint or "Dein Browser unterstützt keine Kamera. Nimm Safari oder Chrome."

**`start()`**
1. Stop the old tracks (iOS cannot hold two cameras).
2. Set `srcObject` and `play()`, ignoring errors.
3. `waitForVideo`: needs `readyState ≥ 2 && videoWidth > 0`; listens to `loadeddata`/`resize`; after a 10 s timeout, `CameraError('timeout','Die Kamera startet nicht. Lade die Seite neu.')`.
4. Read `track.getSettings().facingMode`.
5. `cameras = count(enumerateDevices videoinput) || null`.

**Facing.**
- `facing` = the reported `facingMode` if it is `user` or `environment`.
- Else, if `cameras === 1`, then `'user'`: a single webcam faces the guest and is mirrored like a video call.
- Otherwise the requested value stays.

**Getters.**
- `mirrored === (facing === 'user')`
- `canSwitch === (cameras !== 1)` (unknown counts as true)
- `live` = some video track has `readyState 'live'`
- `width` / `height` = `videoWidth` / `videoHeight`

**Methods.**
- `switchFacing()` toggles the facing and calls `start()`.
- A `visibilitychange` to visible restarts the stream if it is not live (iOS kills streams in background tabs).

**`cameraErrorMessage(err)`**
- Order: insecure context ("…nur über eine sichere Verbindung (https)."), then in-app browser (`IN_APP_HINT`), then the error type:
  - `NotAllowedError`/`SecurityError`:
    - iOS: "…„aA“ › Website-Einstellungen › Kamera › Erlauben…"
    - touch: "…Tippe auf das Schloss…"
    - desktop: "…Klick in der Adressleiste auf das Kamera-Symbol…"
  - `NotFound`/`Overconstrained`: "Keine passende Kamera gefunden."
  - `NotReadable`/`Abort`: "Die Kamera wird gerade von einer anderen App benutzt…"
  - otherwise: "Die Kamera konnte nicht gestartet werden."
- In-app UA regex: `/Instagram|FBAN|FBAV|FB_IAB|Line\/|Snapchat|TikTok|musical_ly|Twitter|LinkedInApp|GSA\//i`.
- `isIOS`: `/iPad|iPhone|iPod/` or (MacIntel && `maxTouchPoints > 1`).

**`captureFrame(video, tw, th, {mirror, canvas})`** is the cover crop, centred:
```
scale = max(tw/vw, th/vh); sw = tw/scale; sh = th/scale; sx = (vw-sw)/2; sy = (vh-sh)/2
if mirror: ctx.translate(tw,0); ctx.scale(-1,1)
ctx.drawImage(video, sx, sy, sw, sh, 0, 0, tw, th)
```
The preview must show the same region: CSS `object-fit: cover` with the default centred `object-position`, and `transform: scaleX(-1)` exactly when `cam.mirrored`. **The saved photo is mirrored for the front camera, so preview equals photo.** The desktop e2e test checks the mirrored centre crop of a test card.

**Requested resolutions.** Beer: 1920×1440, environment. Booth: 1440×1080, user. Both are 4:3, so the 3:4 crop keeps the full sensor height.

### 4.2 Beer Cam overlay (`shapes.js`)

- Paths live in **photo space**, 1080×1440. The SVG uses `viewBox 0 0 1080 1440` with `preserveAspectRatio="none"`, laid over the 3:4 box, so overlay = photo.
- `SHAPES`:
  - **bottle**: a German 0.5 l "Euroflasche". Box `[364,100,352,1240]`; outline, cap and label details, shine.
  - **cup**: a 0.5 l party cup. Box `[214,220,652,1100]`; foam and ridges.
  - Each has `label` (Flasche/Becher) and `hint` ("Halte deine Flasche/deinen Becher genau in den Umriss").
- The darkening path is the even-odd rectangle minus the silhouette. Strokes use `vector-effect: non-scaling-stroke`.
- `vesselIcon` uses the bounding box as `viewBox` with `xMidYMax meet`.
- Visual rules in CSS: the guides fade outside `camera`/`loading`, and the line animates.
- **The capture region equals the visible box:** `.beer-frame` is exactly 3:4, the video is cover-fitted and centred inside it, and `captureFrame` crops the same centred 3:4. Tests check the video and overlay boxes equal the frame (±1 px), the bottle line is >0.8× and the cup >0.7× of the frame height, both centred.

### 4.3 Fotobox renderer (`renderer.js`)

**`coverCrop(vw, vh)`** returns the visible region in texture coordinates `{x,y,w,h}`. With `ASPECT = 0.75`:
- if `vw/vh > ASPECT`: `w = ASPECT/a`, `x = (1-w)/2`, `y = 0`, `h = 1`
- else: `h = a/ASPECT`, `y = (1-h)/2`, `x = 0`, `w = 1`

**WebGL1.**
- Context: `canvas.getContext('webgl'|'experimental-webgl', {alpha:false, antialias:false, depth:false, stencil:false, premultipliedAlpha:false, preserveDrawingBuffer:false})`.
- Vertex shader: a full-screen quad strip; `v_uv = (x*.5+.5, .5-y*.5)` so (0,0) is top-left; `gl_Position.y *= u_flipY`.
- `PRELUDE`:
  - `precision highp` if available
  - uniforms: `u_video`, `u_overlay`, `u_crop` (vec4 xy offset, zw size), `u_mirror` (float, 1 = mirror the **video only**), `u_time` (s, `((now - t0)/1000) % 1000`), `u_px` (one camera pixel in uv: `1/max(1, crop.w*vw)`, `1/max(1, crop.h*vh)`)
  - `const OUT = vec2(1080,1440)`
  - helpers: `video(uv)` (clamp; mirror x; `texture2D(u_video, crop.xy + uv*crop.zw)`), `luma` (601 weights), `saturation`, `contrast`, `scurve`, `vignette(uv, amt)` (aspect-corrected, `smoothstep(.25,.7)`), `hash` (sin-free), `rgb2hsv`, `hsv2rgb`
- `MAIN`: `c = clamp(effect(v_uv))`; `o = texture2D(u_overlay, v_uv)` (premultiplied); `gl_FragColor = vec4(c*(1-o.a) + o.rgb, 1)`.
- Custom uniforms per filter via `filter.uniforms`. A value is a number, vec2/3/4, or a vec3 array (length % 3); functions are evaluated with `{mirror, time}`.
- Textures are NPOT with `CLAMP_TO_EDGE` and `LINEAR`. The overlay is uploaded with `UNPACK_PREMULTIPLY_ALPHA_WEBGL=true`.
- Programs are cached per filter id. Compiling happens in `setFilter`, so errors surface there; compile errors are ignored if the context is lost.
- Context loss: `webglcontextlost` calls `preventDefault` and sets `lost`; `webglcontextrestored` runs `setup()` and re-applies the filter (tested by `test_survives_webgl_context_loss`).
- **`render(video, {mirror, time})`**: uploads the video frame (only when `readyState ≥ 2`), then draws at canvas size with `flipY = 1`. Returns whether something was drawn.
- **`capture()`**:
  1. Create an RGBA texture of 1080×1440 (`NEAREST`) and an FBO; check completeness.
  2. `draw(W, H, flipY = -1)` (because `readPixels` returns rows bottom-up), then `readPixels`.
  3. `putImageData` into **one reused 2D canvas** (iOS caps total canvas memory). It is valid until the next capture.
  4. The FBO and texture are deleted and the viewport restored.
- The same video texture (the last uploaded frame), `u_time` and overlay are used as in the frozen preview, so **WYSIWYG** holds. Patterns are defined in output space (`uv*OUT`), not screen pixels.

**Canvas2D fallback** (`?renderer=canvas2d`, or automatically when WebGL is missing or the base shader fails; a fresh canvas replaces the old one because a canvas keeps its first context type):
- `drawImage` with the crop and mirror, then `filter.cpu(ctx,w,h,state)` (`getImageData` per-pixel ops), then the overlay `drawImage` scaled.
- `willReadFrequently: true`.
- The preview is capped at 480 px wide; capture is 1080×1440 into the shared canvas.

### 4.4 Filters and overlays (`filters.js`, `overlays.js`)

| id | GLSL | CPU fallback | Overlay |
|---|---|---|---|
| normal | `video(uv)` | `fallback:true` | — |
| bw | `scurve(luma, .75) * vignette(.35)` | yes | — |
| sepia | 3-stop tone map + grain `hash(floor(uv*OUT/2))` + vignette .45 | yes | — |
| colorpop | keeps reds (hue≈8°, sat .45–.62, val .25–.4), else greyscale `scurve(.5)`; sat 1.35 | yes | — |
| party | sat 1.2, contrast 1.05 | `fallback:true` | `partyFrame` |
| emoji | sat 1.15, contrast 1.04 | `fallback:true` | `emojiProps` |
| neon | luma → night/pink/cyan ramp + vignette .3 | yes (LUT) | — |
| vhs | line jitter `hash(line, floor(t*15))`, RGB shift .0035, warm faded blacks, scanlines, grain, vignette .5 | **no** (hidden in Canvas2D) | `vhsOverlay` |
| retro | 72×96 cells, 4-tap average, 2×2 Bayer dither, nearest PICO-8 colour (`u_palette vec3[16]`, weighted distance) | **no** | `retroHud` |
| comic | Sobel edges (`u_px*1.5`), posterize ×4, 45° halftone dots (12 px output), dark ink edges | **no** | `comicOverlay` |

**Overlays** are drawn **once per filter selection** into a transparent 1080×1440 canvas, which is reused. They are **never mirrored**. A deterministic `seeded()` PRNG (mulberry32) keeps them identical every time.
- **party:**
  - frame: gradient #ff3d8b → #ff8a00 → #ffd23f; borders side 52, top 52, bottom 236
  - 420 confetti pieces outside the window; a rounded window (radius 44) cut out with `destination-out` plus a white stroke of 10
  - title: `fitFont` (max 112, min 48, ellipsis), outlined `#4a0d6b`
  - line `"DD.MM.YYYY  ·  📸 Fotobox"`
- **emoji:** 300 confetti pieces at the edges plus 9 rotated emoji stickers placed around the face.
- **vhs:** ● REC, battery, VCR date `"MÄR. 05 2026"`, SP, ▶ PLAY, with chromatic offset text in the mono font.
- **retro:** 5×7 pixel font (A–Z, 0–9, `!?-.:'&#+` and space; transliterates Ä→AE, Ö→OE, Ü→UE, ß→SS, É/È→E, À→A); 1UP with 3 hearts, HI-SCORE 999999, and the party name (≤26 chars, cut at a word, cell size 6–14 px) with drop shadows.
- **comic:** a "WOW!" 12-point star burst top right.

Font stacks are system fonts only (CSP `font-src 'self'`). A test checks that a long party name with umlauts and emoji renders.

**Catalogue merge.** `buildFilterList(catalogue, mode)` merges `filters.json` (order, name, icon) with the implementations by id. It skips ids that have no implementation, and in Canvas2D mode skips filters with neither `cpu` nor `fallback`.

### 4.5 Outbox (`outbox.js`)

- IndexedDB `vb-booth`, version 1, store `outbox`, keyPath `id`.
- **`keep({id, blob, meta})`** stores `{id, meta, at: Date.now(), type, data: Blob}`. If that fails (older WebKit cannot store Blobs) it retries with `data: ArrayBuffer`. Returns a bool and never throws.
- **`forget(id)`** never throws.
- **`kept()`** returns valid records sorted by `at`, rebuilding Blobs; `[]` on any failure.
- The tests read this exact schema.

### 4.6 `device.js` (traits)

- Components:
  - `ua`, `platform`, `languages` (joined with ","), `timezone`
  - `screen` = `"{max(w,h)}x{min(w,h)}@{dpr}"`, `color_depth`
  - `cores` (`hardwareConcurrency`), `memory` (`deviceMemory`), `touch` (`maxTouchPoints`)
  - `gl_vendor` / `gl_renderer` (`WEBGL_debug_renderer_info` unmasked when available), `gl_max_texture`
  - `canvas` = the first 16 hex chars of sha256 of a fixed canvas drawing's dataURL
- `hash` = sha256 of the sorted `"k=v"` pairs joined by `"|"`. Without `crypto.subtle` (plain http on a LAN IP) it falls back to a double FNV-1a, repeated to 64 hex.
- The result is cached as a promise and never rejects (fallback `{hash(UA), components:{ua, fallback:true}}`).
- `vb.getFingerprint()` loads it **only through dynamic `import('./device.js')`** in try/catch. If that fails, the hash is built from `UA|lang|screen|tz` with `components {ua, fallback:true}`. Consent requires a fingerprint.

### 4.7 What to port as framework-agnostic TypeScript modules

1. `core/camera.ts`: everything in camera.js, unchanged in behaviour (constraint shapes, retry, facing inference, `canSwitch`, mirror, visibility restart, German messages).
2. `core/device.ts`: dynamically imported, **neutral file and chunk name** (no "fingerprint").
3. `core/api.ts`: `api`, `ApiError`, `errorFromResponse`, the `Retry-After` formatting, the network/offline distinction, `scan_qr` → reload, and XHR `uploadJpeg` with progress and timeout.
4. `core/media.ts`: `captureFrame`, `canvasToJpeg`, `saveImage` (share sheet on iOS).
5. `core/identity.ts`: the boot state machine (identify, consent, uid storage), the user store with `onUserChange`, the pause/stop hint state machine with 30 s and visibility rechecks, and `normalize`/paste-link handling.
6. `core/feedback.ts`: confetti (canvas), flash, vibrate. `core/debug.ts`: the panel.
7. `beer/shapes.ts`: path data and the 1080×1440 space.
8. `booth/renderer.ts`, `booth/filters.ts` (GLSL strings plus CPU ops), `booth/overlays.ts`, `booth/outbox.ts`, and the catalogue JSON. Keep it the single source of truth, read by the backend.
9. Admin pure logic: `relTime`, `absTime`, `clock`, `describeUA`, `safeNext`, `qs`, the SSE `connectEvents` state machine, PhotoCollection ordering semantics (newest first by `created_at` string), the resync-window deletion rule, and the throttle (not debounce) semantics.
10. `loader.js` stays a **plain classic script** that is copied, not bundled.

---

## 5. Security and robustness invariants (checklist)

**CSP and page rules**
- [ ] CSP exactly as in §2.1. No inline `<script>`, `<style>`, `style=""` or `on*=`; no `eval` / `new Function`; no CDN, external font or external URL.
  - Setting `el.style.x` or CSSOM from JS is allowed.
  - **Any runtime CSP violation fails the e2e tests**, because `page.js_errors` must be empty.
  - A build must emit external CSS and JS only. A dev server that injects `<style>` needs a dev-only CSP relaxation.
- [ ] No `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write` with data. This is tested on the admin JS; keep the intent for sources.
- [ ] `img-src 'self' blob: data:` (result previews, toDataURL), `media-src 'self' blob:`, `connect-src 'self'`, `frame-ancestors 'none'` plus `X-Frame-Options DENY`, `Permissions-Policy camera=(self)`, COOP/CORP same-origin, `nosniff`, `Referrer-Policy: no-referrer` (protects the token), HSTS on https.

**Cookies and tokens**
- [ ] Cookies as in §2.1. Admin is `SameSite=Strict`. The access cookie is derived from the token, so rotating the token locks everyone out. The admin session dies on password change via `pw_tag`.
- [ ] All secret comparisons go through `constant_time_equals` (sha256 both sides, then `compare_digest`). `Signer.unsign` rejects values over 256 characters or without a dot; the admin cookie is limited to 128 characters.
- [ ] Token handling:
  - `?t=` is accepted only on GET page paths, then a 303 strips it.
  - `//` is collapsed, so there is no open redirect.
  - The access log masks `([?&]t=)[^&\s"]*` as `***` and drops `/healthz`.
  - The QR tool never prints the token (`<token>`).
  - `Settings`: token 16–128 chars `[A-Za-z0-9_-]`, admin password ≥ 12, secret ≥ 32, `cookie_secure` ∈ auto/true/false. The app warns if `cookie_secure=false` while the public URL is https.

**Request handling**
- [ ] CSRF: Origin, or Referer, must equal Host (or be allow-listed) for **every** unsafe method on every path, uploads and login included.
- [ ] Body caps: JSON at most 64 KiB with a mandatory Content-Length (no chunked); uploads use the streaming cap `max_bytes` (8 MB default); `X-VB-Meta` at most 2048; Pillow `MAX_IMAGE_PIXELS = 25M`.
- [ ] Rate limiters (in-memory token buckets, burst = rate; **requires one process and one worker**):

| Limiter | Key | Limit | Charged |
|---|---|---|---|
| `api_guest` | `uid:<public_id>` | 300/min | every `/api` request by an identified device (not admin) |
| `api_ip` | client IP | 1200/min | every `/api` request without a uid (not admin) |
| `new_user_ip` | IP | 120/10 min | each new identity at join |
| `upload_user` | `user:<id>` | 10/min | every upload attempt past content-type |
| `upload_ip` | IP | 180/min | checked before decoding, charged after a valid image |
| `upload_global` | `"global"` | 300/min | same |
| `login_ip` | IP | 5/min | every login |
| `login_ip_hourly` | IP | 20/h | every login |
| `login_failures_global` | `"global"` | 50/h | wrong passwords; only refuses wrong ones |

  The client IP comes from `request.client.host`, which uvicorn rewrites from `X-Forwarded-For` only for `--forwarded-allow-ips`.
- [ ] Upload validation as in §2.5. The re-encode strips EXIF and GPS. Writes are atomic. The per-extension `seq` is never reused (tombstones). Server-side `exact_size` 1080×1440 for both extensions.

**Media and moderation**
- [ ] Media access: random public id (regex) lookup, never by path. Admin sees everything; otherwise access plus owner only. 404 otherwise, without revealing existence.
- [ ] Moderation semantics:
  - A ban hides photos with `reason 'ban'`; unban restores exactly those.
  - A fingerprint ban makes new identities start banned; lifting it auto-releases them.
  - Pauses: per guest, new-guest lock (restore or keep), stop all. Precedence: `banned` > `uploads_paused` > `uploads_stopped`.
  - Live can only hide (a static test enforces this).

**Content blockers** (Appendix B §5)
- [ ] URL paths contain none of `fingerprint track analytic telemetry beacon pixel advert /ads /ad/ collect consent cookie gdpr banner notice modal backdrop privacy popup`.
- [ ] Served file names don't match `/fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]/i`.
  - **Beware bundler hashes:** a hash ending in `ad` before `.js` matches. Use a build-time guard that renames or fails.
  - Names like `upload.js`, `download-*`, `Thread.js` and `Load.js` also match, because they end in "ad." / "ad-".
- [ ] No element class, id or test id matches a generic cosmetic rule (`.cookie*`, `*gdpr*`, `#app > .cookie`, `.blocker-notice`, `.blocker-overlay`, `*-overlay` from the lists, `.appBanner`, `.modal-push`, …).
- [ ] The join dialog keeps `data-testid="join"` with `role="dialog"` inside. None of its `class`, `id`, `data-testid`, `aria-labelledby`, `for` or `name` values contain `consent cookie gdpr banner notice modal backdrop privacy popup`. So no framework `Modal`/`Backdrop` class names there.
- [ ] Optional modules (`device`) load by dynamic import inside try/catch. The main module failing must surface through `loader.js`.

**Watchdog, database, deploy**
- [ ] Loader watchdog: a classic script, 6 s, `window.__vbReady` (or an equivalent flag set once the app graph evaluated), with the `load-failed` notice containing "Blocker".
- [ ] DB migrations: `db.MIGRATIONS` is an append-only list of `(version, script)`.
  - Each step runs in `BEGIN IMMEDIATE`, re-reads `user_version` inside, executes the statements, sets `user_version`, commits. On error it rolls back to the previous version.
  - A newer DB than the code knows is left alone.
  - CLI tools that open the DB also migrate it.
  - `tests/test_core_db_migration.py` upgrades a v1 DB with data.
- [ ] Pure ASGI middlewares, so SSE is not buffered. `X-Accel-Buffering: no`; one uvicorn worker; `timeout_graceful_shutdown 5`; no `server` header.
- [ ] Container: uid 10001, read-only rootfs, tmpfs /tmp, `cap_drop ALL`, `no-new-privileges`, healthcheck `/healthz`. Tools never use /tmp; they write under `<data>/exports/`.

---

## 6. Test suite map (summary; the full detail is in Appendix B)

**Running the tests.**
- `pytest` runs unit and API only (`addopts -m 'not e2e'`).
- `pytest -m e2e` runs Chromium with the fake camera. `VB_E2E_BROWSER=firefox` switches to Firefox.
- `tests/e2e/run_webkit.sh` runs WebKit in `mcr.microsoft.com/playwright/python:v1.63.0-noble`: the repo is mounted read-only, copied, then `pip install -e .`. **There is no Node or build step.**
- `VB_BLOCKLISTS=<dir>` adds the 28 full filter lists.

**Fixtures.**
- `tests/conftest.py`:
  - Constants: `PARTY_TOKEN`, `ADMIN_PASSWORD`, `SECRET_KEY`, `BASE_URL http://testserver`, `ORIGIN`, `JPEG` headers.
  - Helpers: `jpeg()`, `png()`, `fp(n)`, `scan()`, `accept_consent()`.
  - Fixtures: `settings`, `demo_extension` (meta `mood`), `extensions` (overridable), `app`, `core`, `make_client`, `client`, `guest(instagram, fp_n)`, `admin`.
- `tests/e2e/conftest.py`:
  - `live`: a real uvicorn in a thread on a free port, same process, so `live.core` is reachable; `.url()`, `.entry()`.
  - Browser fixtures: session `playwright` and `browser`; `context`, `page` (`track_errors` → `page.js_errors`), `guest_page`, `admin_page` (logs in via fetch).
  - Device profiles: `MOBILE` (Pixel 7 UA, 390×844), `FIREFOX`, `IPHONE` (WebKit), `DESKTOP` 1280×800.
  - `PHONE_CAMERAS` init script: fakes a front and back camera by patching `getSettings().facingMode` and `enumerateDevices`.
  - `WEBCAM` init script (desktop): a 1280×720 canvas test card (red, a blue centre 3:4 column, a yellow square); throws `OverconstrainedError` for `exact` non-user; records `window.__cameraRequests`.
  - Fake cameras: Chromium uses `--use-fake-device-for-media-stream` and `--use-fake-ui-for-media-stream`, plus `VB_FAKE_VIDEO` → `--use-file-for-fake-video-capture` (no Y4M is generated). Firefox uses `FIREFOX_PREFS` (`media.navigator.streams.fake`, `permission.disabled`, async clipboard). WebKit uses its mock camera.
  - Markers: `needs_clipboard`, `firefox_only`, and `chromium_only` (unused).
  - Helpers: `settle_dialogs` (`.vb-scrim` animations), `accept_consent_in_browser` (`tid:join`, `#vb-join-insta`, button "Alles klar"), `shot()`.

**Per-file counts.** "Functions (cases)" counts `def test_` functions, then collected cases after parametrisation.

| File | Functions (cases) | Covers | Class |
|---|---|---|---|
| test_admin_api.py | 31 (61) | auth on all 22 routes, CSRF, photos, bulk, users, bans, auto-ban, stats, Instagram, audit, extensions, event order | pure API |
| test_admin_pages.py | 10 (25) | page gating, CSP-clean HTML, safe JS rules, import rules, live cannot delete | mostly static frontend source |
| test_admin_upload_controls.py | 17 (18) | pause, lock, stop, persistence, events | pure API |
| test_beer.py | 18 (27) | policy, meta, stats, plus 4 page/source checks | mixed |
| test_booth.py | 14 (31) | meta, filter catalogue, plus 5 page/source checks | mixed |
| test_core_access.py | 38 (55) | gate/token, identify/join/me, Instagram, CSRF, headers, settings, misc | pure API (3 assert gate/404 HTML text) |
| test_core_admin_auth.py | 12 (12) | login, sessions, limits, redirects | pure API |
| test_core_blockers.py | 7 (7) | filter rules vs URLs and elements | static frontend analysis |
| test_core_db_migration.py | 4 (4) | v1→v2, rollback, newer DB | unit (internals) |
| test_core_uploads.py | 16 (16) | pipeline, media, bans, tombstones, bus | pure API |
| test_tools.py | 44 (50) | timelapse, qr, export | unit |
| e2e test_core_e2e.py | 8 | gate, consent, SDK camera and upload, blocked modules | DOM and SDK |
| e2e test_core_ui_e2e.py | 19 (25) | join/Instagram dialogs, chip, home errors, Retry-After, debug, in-app | DOM and SDK |
| e2e test_admin_e2e.py | 23 (27) | login, live/SSE, manage, tabs, user page, bans, lightbox, scroll | DOM (1 HTTP-only) |
| e2e test_admin_a11y_e2e.py | 7 | tabs, confirm, lightbox focus, names, contrast | DOM |
| e2e test_admin_upload_controls_e2e.py | 4 | chip, sheet, guest hint | DOM and SDK |
| e2e test_beer_e2e.py | 20 | flow, layout, errors, bans, shortcuts | DOM |
| e2e test_booth_e2e.py | 34 (35) | renderer, filters, capture fidelity, countdown, outbox, leave sheet, layout | DOM, IndexedDB |
| e2e test_desktop_e2e.py | 5 (6) | PC webcam: crop and mirror, keyboard, admin | DOM |
| e2e test_firefox_e2e.py | 3 (8) | real permission prompt, allow, block | DOM |

**Totals.** Unit: 211 functions / 306 cases. E2E: 123 functions / 140 cases.

**Survival after a frontend rewrite.**
- **A, unchanged:** about 188 unit functions plus 3 e2e (`test_event_stream`, `test_gate_without_token`, `test_static_file_names_avoid_blocker_keywords`).
- **B, static-source tests to retarget:** 23 functions in test_admin_pages, test_beer, test_booth and test_core_blockers. The cosmetic and join-dialog blocker tests need a new DOM extractor; they currently scan `h()` calls, HTML and CSS.
- **C, selector-level:** about 101 e2e functions keep working if the DOM contract is kept: test ids, ids, roles and names, German strings, `data-*` state, and the classes `is-hidden`, `is-mirrored`, `is-fit`, `vb-sheet--more`, `.vb-notice`, `.vb-toast`, `.vb-scrim`, `.adm-badge--*`, `#tab-*`, `#panel-*`.
- **D, rewrite needed (19):**
  - tests that import `/static/core/vb.js` or `camera.js` exports in the page (`sheetOpen`, `uploadJpeg`, `api`, `fatal`, `cameraErrorMessage`);
  - the probe/snap test pages built on the SDK;
  - tests that route `device.js` or `vb.js` by URL;
  - tests that remove `.vb-scrim` out of band;
  - tests that read IndexedDB `vb-booth/outbox` directly.
  - **Keeping a framework-agnostic SDK at `/static/core/vb.js` and `camera.js` with the same exports, plus the same IndexedDB schema, moves most of D into C.**

**Internals the tests touch** (they break on a backend restructure unless re-exported):
- `virtubooth.{app.create_app, config.Settings/ConfigError, context.Core/Limits, extension.*, repo.{PhotoQuery, Repo, Photo, User, PAUSE_*}, db (MIGRATIONS/SCHEMA/SCHEMA_VERSION/Database, monkeypatched), events.{EventBus, format_sse}, names.pseudonym, identity.normalize_instagram, errors.ApiError, security.origin_allowed, logs.AccessLogFilter, admin.queries.AUTO_BAN_REASON, admin.api.router (FastAPI internals) and SESSION_RECHECK_SECONDS, ratelimit.RateLimiter, pages.{STATIC_DIR, ADMIN_STATIC}, extensions.beer/booth (FILTERS, load_filters), tools.*}`.
- About 40 `core.repo` methods, `core.db` raw SQL, `core.limits.<name>` replaced, and `core.settings` replaced.

**Coverage gaps:**
- No test for the SSE overflow behaviour beyond the "drop" itself.
- No test for `/api/admin/events` resume.
- No visual regression tests beyond a few pixel checks.
- No a11y tests on guest pages beyond the dialogs.
- Firefox and WebKit are not in the default run.

---

## 7. Backend problems and refactor opportunities

**Layering.**
- Routes hold business logic:
  - the upload pipeline (`uploads.store_photo`, rate-limit orchestration)
  - ban, unban and auto-ban release (`admin/api._release_auto_banned`)
  - join (fp-ban check, lock); event publishing; response shaping
- `repo.py` mixes persistence, file IO (`delete_photo` unlinks files **inside** the transaction before COMMIT), audit logging (in **separate** transactions after the write, so not atomic), settings KV and session storage.
- Proposal:
  - A `services/` layer (identity, uploads, moderation, upload_controls, admin_auth) that owns transactions, audit and event publishing.
  - Repositories per aggregate: users, fingerprints/bans, photos, settings, sessions, audit, plus `admin_read_models` absorbing `admin/queries.py`.
  - Thin routers.

**Serialisation and schemas.**
- `guest_view` and `admin_view` live on domain dataclasses; `_user_views` adds fields in the router; `guest_photo_view` lives in uploads.py.
- No `response_model` anywhere; OpenAPI is disabled (`docs_url`, `redoc_url`, `openapi_url = None`).
- Proposal:
  - Pydantic response models for every route (§2.2 is the target).
  - An `ErrorBody` model with a `code` Literal enum, documented through `responses=`.
  - Discriminated-union models for SSE events.
  - Keep the runtime docs off, but add `virtubooth openapi > openapi.json` (or a test that exports it), and generate TS types (`openapi-typescript`) plus event types from the JSON schema in the frontend build.
  - A contract test that diffs the schema.

**Naming and module boundaries.**
- `pages.py` contains the API route `/api/extensions`.
- `admin_auth.py` sits at the top level while the admin API lives in `admin/`.
- `middleware.py` imports `pages.gate_page`. `GuardMiddleware` combines 4 concerns.
- `deps.py` holds auth plus cookie parsing.
- Proposal:

```
backend/virtubooth/
  app.py
  config.py
  core/        security, signing, ratelimit, events, errors, logging
  db/          connection, migrations/0001_initial.sql, 0002_upload_pauses.sql
  domain/      models, constants (AUTO_BAN_REASON, PAUSE_*, PHOTO_SIZE)
  repositories/
  services/
  api/         deps, schemas, routers/{guest, media, admin_auth, admin_photos,
               admin_users, admin_bans, admin_overview, admin_events, upload_controls}
  web/         pages (gate/notfound/static serving), middleware/{token_entry, csrf, body_limit, api_budget, headers}
  extensions/  sdk.py + registry.py + beer/, booth/
  tools/
```

  Keep compatibility re-exports (`virtubooth.repo`, `virtubooth.db.MIGRATIONS`, …) while the tests are migrated.

**Duplication** (§1.4). Centralise the id regexes as `Annotated` types, `AUTO_BAN_REASON`, the 1080×1440 constants, `FACINGS`, `_user_or_404`, `MAX_ID`, `count_photos`, and the SSE response helper.

**Inconsistencies to fix or document:**
- **`user.uploads_changed`** carries `AdminUser` without `auto_banned`/`auto_ban`, while `user.banned` carries `AdminUserView`. `photo.user` also lacks `auto_banned`, so photo cards cannot show AUTO-GESPERRT.
- **Cursor and paging:**
  - `next` is non-null when a page is exactly full, which costs one extra empty fetch.
  - `total` appears only on the first page.
  - Three cursor styles are in use: photo public id, numeric offset, audit numeric id.
- **Response and error shapes:**
  - `DELETE /photos` returns `{ok, id}` while hide returns `{photo, changed}`.
  - `login_locked` has no `Retry-After`.
  - Unknown `/api` paths give `http_404` rather than `scan_qr`; the docs claim otherwise.
  - `/media` errors are JSON on a non-API path.
- **Lock state:** `PauseState.period` is null while disabled, although the DB keeps the counter.
- **`unhide` vs bans:** unhide also un-hides a `ban`-hidden photo of a still-banned user. Possibly intended, but undocumented.
- **Instagram editing:** `PATCH /api/me` is refused for banned users with a "gesperrt für Uploads" message, which is confusing on the Instagram editor.

**Robustness bugs:**
1. **EventBus overflow.** `_fanout` discards a full queue, but `sse_stream` keeps awaiting that orphaned queue. It drains up to 256 events, then sends only pings forever. The client shows "Echtzeit" and never receives events or reconnects. Fix: on overflow, enqueue a sentinel or close the stream so the client reconnects and resyncs; optionally add a small replay ring buffer keyed by event id and `Last-Event-ID`.
2. **Admin pages miss events** between the first fetch and the SSE open. Fix: subscribe first, or support replay.
3. **Audit atomicity:** ban, unban and others commit, then audit in a new transaction.
4. **`delete_photo` unlinks files before COMMIT.** Unlink after commit, or tolerate a dangling row.

**Extension interface (backend and frontend coupling).**
- `Extension.static_dir` couples the Python package to hand-written frontend files.
  - `validate_extension` requires `static_dir/index.html`.
  - Pages import `/static/core/vb.js` by absolute URL.
  - `filters.json` is shared between backend validation and frontend fetch.
- With a TS build, extension frontends move into the frontend workspace (e.g. `frontend/src/extensions/{beer,booth}`) and build to `dist/x/<id>/index.html`.
  - The backend `Extension` should reference a built page directory (`page_dir` resolved from a configurable `VB_FRONTEND_DIST`, or a package-data path) instead of `static_dir`.
  - `validate_extension` should check the build output.
  - `filters.json` should move to a shared `contracts/` location, imported by TS at build time with type checks and read by Python. It must still be served or inlined; today the page fetches `./filters.json`.
- `meta_keys` and `validate_meta` should become a pydantic model per extension, exported to TS so the frontend sends typed meta.

**Tools package.**
- Duplicate env parsing (`_common.env_list`, `qr` reading `VB_PUBLIC_BASE_URL`/`VB_PARTY_TOKEN`/`VB_PARTY_NAME` directly) instead of a shared partial-settings loader.
- Raw SQL in `photo_counts`.
- Opening the DB runs migrations. That is fine, but document it.
- Keep `python -m virtubooth.tools.<x>` entry points, since README and DEPLOY commands depend on them. Optionally add `virtubooth tools <x>` subcommands.

**Config.** A hand-rolled `from_env` with repeated defaults. Use a declarative field table (or pydantic-settings) and add frontend-related settings: dist path, dev CSP relaxation, and asset cache policy.

**Static caching.** Everything is `no-cache`. With hashed bundles, serve the assets directory with `Cache-Control: public, max-age=31536000, immutable` and keep HTML `no-cache`.

**Error handling.** Error codes are strings scattered over modules, and the frontend rewrites some messages (rate limit). Create one `ErrorCode` enum and message catalogue, exported to TS.

**Testability.** `create_app(settings, extensions)` is already good. Add clock injection (rate limiter, `now_iso`). Make `Limits` and the bus injectable. Keep `app.state.core` or provide a test accessor.

---

## 8. Data model

SQLite `<data>/virtubooth.db` with WAL, `synchronous=NORMAL`, `foreign_keys=ON` and `busy_timeout=5000`. One shared connection behind an RLock. `PRAGMA user_version` = 2.

| Table | Columns (type, constraints) | Indexes |
|---|---|---|
| `users` | `id` INTEGER PK; `public_id` TEXT NOT NULL UNIQUE; `name` TEXT ('' then pseudonym from id); `created_at`, `last_seen_at`, `consent_at`, `consent_version` TEXT NOT NULL; `instagram` TEXT NULL; `fp_hash` TEXT NULL (current); `fp_components` TEXT JSON '{}'; `first_ip`, `last_ip`, `user_agent` TEXT ''; `banned_at` TEXT NULL; `ban_reason` TEXT NULL; **v2:** `uploads_paused_at` TEXT NULL, `uploads_paused_source` TEXT NULL (`admin` / `new_guest_lock`), `uploads_lock_period` INTEGER NULL | `users_fp(fp_hash)`; v2 partial `users_lock_period(uploads_lock_period) WHERE NOT NULL` |
| `user_fingerprints` | `user_id` FK → users ON DELETE CASCADE; `fp_hash`; `first_seen`; `last_seen`; PK(`user_id`, `fp_hash`) | `user_fingerprints_fp(fp_hash)` |
| `fingerprint_bans` | `fp_hash` PK; `created_at`; `reason` ''; `source_user_id` FK → users ON DELETE SET NULL | — |
| `photos` | `id` INTEGER PK (also the time order and internal cursor); `public_id` UNIQUE; `extension`; `user_id` FK → users; `seq` (UNIQUE with extension; never reused); `filename`, `thumb_filename` (relative to `<data>/<ext>/`); `created_at`; `width`; `height`; `bytes`; `meta` TEXT JSON; `hidden_at`; `hidden_reason` ('admin' / 'ban'); `deleted_at` (tombstone) | `photos_ext_created(extension, created_at)`, `photos_user(user_id)` |
| `admin_sessions` | `token_hash` PK (sha256); `created_at`; `expires_at`; `pw_tag`; `ip`; `user_agent` | — (expired rows are purged on each login) |
| `audit_log` | `id` PK; `at`; `actor`; `action`; `target` ''; `details` TEXT JSON '{}' | — |
| `settings` (v2) | `key` PK; `value` TEXT JSON; `updated_at` | — |

**Settings keys.**
- `upload_pause` = `{enabled, since, period, by}`. The period counter persists when disabled.
- `upload_stop` = `{enabled, since, by}`.

**Migrations.** `MIGRATIONS = ((1, SCHEMA), (2, SCHEMA_V2))`. v1 uses `IF NOT EXISTS`; v2 does `ALTER TABLE` and creates `settings`. The next change must be `(3, …)` appended.

**Files.**
- `<data>/<ext>/<YYYYmmdd-HHMMSS-mmm>_<6hex>.jpg` and `<data>/<ext>/thumbs/<same>.jpg`.
- `<data>/exports/` (qr/, timelapse mp4, export tar.gz, temporary `.vb-*` dirs).

**What the frontend needs.**
- **Guest:** only `GuestUser`, `uploads_stopped`, the consent text, `PublicExtension[]`, upload results, and beer stats. **There is no "my photos" endpoint**, even though `/media` lets owners view their photos. This is a feature gap if a gallery is wanted.
- **Admin:** `AdminPhoto`, `AdminUserView`, `UserRef`, fingerprint and ban lists, stats, Instagram aggregates, audit, the extension labels (`meta_labels` to render `meta`), pause and stop state, and SSE. Everything in §2.

---

## 9. Risks for the rewrite (most likely regressions)

1. **CSP violations at runtime.** Framework or dev tooling that injects `<style>` (CSS-in-JS, some transition systems, Vite dev HMR), inline module-preload scripts, or `style=` in SSR markup. Every e2e test asserts zero console errors. Choose a stack whose **production** output is pure external JS and CSS, and give the dev server its own CSP.
2. **Content-blocker names.** Hashed chunk names hitting `ads?[-_./]` by chance; component-derived chunk or class names (`Modal`, `Backdrop`, `Notice`, `Banner`, `Popup`, `Cookie`, `Consent`, `Privacy`); CSS-module hashed class names that defeat the cosmetic scanner. Add a build-time name guard and keep semantic, neutral class names on guest-facing UI, above all the join dialog.
3. **Loading resilience.** Bundling `device.js` into the main chunk (one blocked URL then kills the app); losing the classic `loader.js` watchdog; losing the dynamic-import fallback fingerprint.
4. **Camera WYSIWYG.**
   - The preview's CSS crop or mirror diverging from `captureFrame` or `coverCrop`.
   - Not freezing the preview before capture.
   - Rendering the overlay mirrored.
   - Changing the requested constraints (tests assert exact shapes).
   - The iOS specifics: `playsinline`, `muted`, the video kept in the DOM at opacity 0.001, the restart on visibility, the `play()` nudge, one reused capture canvas, `toBlob` only.
5. **Exact output size.** The server rejects anything that is not 1080×1440. DPR or resize bugs in a new canvas pipeline become 400s.
6. **Beer number semantics.** The success number and counter show the **visible board count** (`total`), not `seq`. Easy to "fix" wrongly.
7. **Dialog and keyboard semantics.**
   - The join dialog has no dismiss and focuses the dialog, not the input.
   - Shortcuts are suppressed while any `.vb-scrim` or `.vb-notice` exists.
   - Space/Enter shoot only when focus is on body.
   - Booth arrows also work from the strip and the shutter.
   - Admin confirm focuses Cancel; capture-phase Escape keeps the lightbox from closing too.
   - Lightbox history and Back closes it, with the `closing` guard against a double `history.back()`.
   - Focus restoration across re-renders, which today relies on test ids and labels.
   - A virtual-DOM framework may fight the tests' out-of-band removal of `.vb-scrim`.
8. **Offline and outbox.** IndexedDB schema compatibility (existing phones may hold records in `vb-booth`/`outbox`); the Blob→ArrayBuffer fallback; the permanent vs transient error split; keep-stored on paused or banned; `beforeunload` only when not stored; retry on `online`; resume on the next visit.
9. **Error messaging.** `fatal()` distinguishing offline vs blocked vs API vs camera, never showing raw errors; the `Retry-After` suffix format; per-page rate-limit texts and countdown retry buttons; `scan_qr` → reload; `consent_outdated` → reload after 1.5 s; `needs_consent` mid-session → re-join and retry.
10. **Admin realtime.** The SSE reconnect, polling and visibility state machine; the resync window deletion logic; counting deletes once (API answer plus event); stale-response guards (`reqId`); throttle vs debounce; the "new photos" pill semantics differing between live and manage.
11. **Server-side gating and routing.**
    - An SPA catch-all must not replace the gate (HTTP 404), the notfound page (404), or the admin 303 redirect with `next` (query encoded).
    - `/x/<id>` 308.
    - Per-extension pages under `/x/<id>/`.
    - Unknown `/api` paths stay JSON.
    - `safeNext` rules (no open redirect; `?id=` survives).
    - **A multi-page build (one entry per page) maps 1:1 to today's server routes.**
12. **Build and deploy pipeline.** The Dockerfile, `.dockerignore` allowlist, hatch wheel contents, `run_webkit.sh` and the e2e fixtures all assume files on disk inside `virtubooth/`. A Node build stage, a dist location and the test bootstrap all need adding, or the e2e suite silently tests stale assets. Coolify builds from the Dockerfile, so the Node stage must live there.
13. **German copy.** Dozens of exact strings are asserted (Appendix B §3), plus pluralisation and number formatting (`de-DE`, "1 Mio.").
14. **Layout guarantees tested in e2e.**
    - Landscape at 844×390 with no scrolling and everything on screen.
    - Small phones (320×460 to 390×844) keep the join button visible.
    - No horizontal scroll anywhere (30-character handles).
    - Desktop tiles centred and filters `is-fit`.
    - Contrast ≥ 4.5 on danger buttons and badges.
    - 44 px touch targets.
15. **Backend refactor and tests.** About 40 `repo` methods, module paths, `db.MIGRATIONS` monkeypatching and `SESSION_RECHECK_SECONDS` are referenced by tests. Restructure behind compatibility re-exports and move the tests in the same wave.

---

**Appendix pointers, again:** the full admin UI inventory (Appendix A) and the full test-suite map (Appendix B) are at the two `tool-results` paths given at the top. They contain every admin string, test id, CSS hook, timer, throttle and bug list, and every e2e selector with the behaviour it asserts.