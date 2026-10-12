# virtubooth architecture

A FastAPI app (one process, one uvicorn worker) serving plain HTML/JS pages.
SQLite + files on disk under `VB_DATA_DIR`. Runs in Docker behind any
TLS-terminating reverse proxy (HTTPS is required for camera access).

```
virtubooth/
├── app.py            create_app(settings, extensions=None): wires everything
├── config.py         Settings (env VB_*)
├── context.py        Core: settings, db, repo, bus, signer, limits, extensions
├── db.py             SQLite schema + locked connection
├── repo.py           ALL data access: users, photos, bans, sessions, audit
├── deps.py           FastAPI dependencies: require_access / require_guest / require_admin
├── security.py       cookies, signing, CSRF origin check, security headers
├── middleware.py     ?t= token entry, CSRF guard, API rate limit, headers
├── identity.py       /api/identify, /api/consent, PATCH /api/me
├── admin_auth.py     /api/admin/login|logout|session
├── uploads.py        POST /api/x/<ext>/upload (generic pipeline)
├── media.py          GET /media/<photo id> (owner or admin only)
├── pages.py          /, /x/<ext>/…, /admin/…, gate + 404 pages
├── events.py         EventBus + sse_response()
├── images.py         JPEG validation + re-encode + thumbnail
├── names.py          pseudonyms ("Durstige Giraffe #17")
├── static/core/      frontend SDK: vb.js, camera.js, device.js, loader.js, vb.css, home
├── admin/            admin API (api.py) + admin UI (static/)
├── extensions/       one package per activity (beer, booth, …)
└── tools/            CLI tools: timelapse, qr, export
```

## Access model

| Who | How | What |
|---|---|---|
| Party guest | scans QR `https://host/<path>?t=<VB_PARTY_TOKEN>` → middleware sets `vb_access` cookie (HMAC of the token, HttpOnly, SameSite=Lax) and 303-redirects to the same URL without `t` | pages, `/api/identify`, `/api/consent` |
| Identified guest | accepted the consent banner → `vb_uid` cookie (signed random public id) + localStorage copy | uploads, own photos, `PATCH /api/me` |
| Admin | `POST /api/admin/login` with `VB_ADMIN_PASSWORD` → `vb_admin` cookie (random token, SHA-256 stored in DB, SameSite=Strict, expires, dies on logout or password change) | `/admin/*` pages, `/api/admin/*`, all media |

- No access cookie → every page shows the "Scan den QR-Code" page (HTTP 404),
  every API call returns 404 `{"error":"scan_qr"}`.
- Rotating `VB_PARTY_TOKEN` invalidates every guest's access.
- **CSRF:** every POST/PUT/PATCH/DELETE must carry a same-origin `Origin` (or
  `Referer`) header, else 403 `bad_origin`. Browsers do this automatically for
  fetch/XHR. Extra allowed origins: `VB_ALLOWED_ORIGINS`.
- **CSP:** `default-src 'self'`, `script-src 'self'`, `style-src 'self'`.
  Pages must not use inline `<script>`, inline `<style>`, `style="..."`
  attributes or `on*=""` handlers. Setting `el.style.foo = …` from JS is fine.
  No CDNs, no external fonts: everything is served from the app.

## Guest identity ("fingerprinting")

There is no registration. Every page calls `boot()` from the SDK:

1. `POST /api/identify {fp, uid}`. Known device (cookie, or the localStorage
   `uid` token) → `{state: "ok"|"banned", user}`. Unknown → `{state:
   "needs_consent", consent}`.
2. Unknown devices see the consent banner (store photos, post on Instagram,
   device recognition; optional Instagram handle). There is no "no" button:
   declining means not using the site. Accepting → `POST /api/consent` creates
   a pseudonymous user (`users` row, name like "Tanzender Waschbär #17").
3. The browser fingerprint (`device.js`: canvas, WebGL renderer, screen,
   timezone, UA, …) is stored per user, history in `user_fingerprints`.
   **It is a moderation hint, not an identity:** identical phone models often
   share a fingerprint. Admins can ban a user (by device id) and, separately
   and with a warning, ban a fingerprint: new identities showing a banned
   fingerprint are created already banned.
4. Banning a user hides all their photos (`hidden_reason='ban'`); unbanning
   restores only those.

## Extension interface

An extension is a package `virtubooth/extensions/<name>/` whose `__init__.py`
exports `extension = Extension(...)` (see `virtubooth/extension.py`). It's
discovered automatically; `VB_EXTENSIONS=beer,booth` restricts and orders.

```python
from pathlib import Path
from fastapi import APIRouter, Depends
from virtubooth.extension import Extension, UploadContext, UploadPolicy
from virtubooth.deps import get_core, require_access

router = APIRouter()

@router.get("/stats", dependencies=[Depends(require_access)])   # → /api/x/beer/stats
def stats(core=Depends(get_core)):
    return {"total": core.repo.count_photos("beer")}

def on_upload(ctx: UploadContext) -> dict:
    return {"beer_number": ctx.photo.seq}

def validate_meta(meta: dict) -> dict:
    if meta.get("vessel") not in ("bottle", "cup"):
        raise ValueError("Unbekanntes Gefäß.")      # → 400 with this message
    return meta

extension = Extension(
    id="beer", title="Beer Cam", emoji="🍺", tagline="…",
    static_dir=Path(__file__).parent / "static",     # must contain index.html
    upload=UploadPolicy(max_side=1440, meta_keys=frozenset({"vessel"}), validate_meta=validate_meta),
    router=router, on_upload=on_upload, order=10,
    meta_labels={"vessel": "Gefäß"},
)
```

What core does for an extension:

- `GET /x/<id>/…` serves `static_dir` (party guests only, traversal-safe).
- `POST /api/x/<id>/upload`: guest + consent + not banned → content type
  `image/jpeg` → rate limits (user/IP/global) → size cap → `X-VB-Meta` header
  (`encodeURIComponent(JSON)`, keys must be in `meta_keys`, values
  str ≤100/number/bool/null, then `validate_meta`) → Pillow decode, size
  checks, re-encode (EXIF stripped) + thumbnail → files
  `data/<id>/<YYYYmmdd-HHMMSS-mmm>_<rand>.jpg` + `thumbs/` → `photos` row with
  per-extension `seq` (never reused) → `on_upload(ctx)` → event
  `photo.created` → `201 {"photo": {id, seq, url, thumb_url, …}, **on_upload_result}`.
- `router` is mounted at `/api/x/<id>`; protect every route with a
  dependency from `virtubooth.deps`.
- Home page tile (`show_on_home`), `/api/extensions`, QR codes (tools/qr).
- Admin UI shows the extension's photos; `meta_labels` names the meta keys.

Data access goes through `core.repo` (`virtubooth/repo.py`). Events:
`core.bus.publish(type, data)`; stream them with `events.sse_response()`.
Core publishes `photo.created` (`{"photo": photo.admin_view()}`) and
`user.created`; the admin API publishes `photo.hidden|unhidden|deleted` and
`user.banned|unbanned`.

## Frontend SDK (`/static/core/vb.js`)

Every page links `/static/core/vb.css`, includes
`<script src="/static/core/loader.js" defer></script>` (shows a hint if the
page's modules never start) and loads its own ES module.

**Content blockers:** uBlock, AdGuard, Brave and iOS content blockers drop
URLs that look like tracking. One failed static import stops every module on
the page, silently. So: neutral file and API path names (no "fingerprint",
"track", "analytics", "beacon", "pixel", "ads", ...; a test checks the file
names), and load optional modules with a dynamic `import()` inside
`try/catch`.

Main API:

| Export | Purpose |
|---|---|
| `boot()` | identify device, show consent banner if needed → `{user, banned}`. Call first. |
| `api(path, {method, json})` | JSON fetch, throws `ApiError` (`.status .code .message`, German message) |
| `uploadJpeg(extId, blob, {meta, onProgress})` | upload with progress → server JSON |
| `openCamera(video, {facing})` | camera controller: `.facing .mirrored .canSwitch .switchFacing() .stop() .width .height`. `facing` is a wish: a PC's only webcam is used either way and counts as `'user'` (mirrored); hide the switch button when `!canSwitch` |
| `captureFrame(video, w, h, {mirror})` | centre-cropped (cover) frame into a canvas |
| `canvasToJpeg(canvas, q)` | canvas → JPEG Blob |
| `saveImage(blob, name)` | iOS: share sheet ("Bild sichern"); else download. Call in a tap handler. |
| `toast(msg, {type})`, `confetti()`, `flash()`, `vibrate()`, `showNotice(emoji, title, text, ...nodes)` | feedback |
| `h(tag, attrs, ...children)` | safe DOM builder (use instead of innerHTML) |
| `mountUserChip(el)`, `editInstagram()`, `getUser()` | guest pseudonym + Instagram handle |
| `isIOS()`, `isInAppBrowser()`, `cameraErrorMessage(err)` | platform helpers |
| `debug(...)` | on-screen log when the page was opened with `?debug=1` |

CSS: tokens `--vb-*`; components `.vb-btn(--primary|--big|--block|--ghost|--danger|--cool)`,
`.vb-icon-btn`, `.vb-shutter`, `.vb-card`, `.vb-chip`, `.vb-input`, `.vb-stage`
(fullscreen camera) with `.vb-topbar`/`.vb-bottombar`, `.vb-modal(-backdrop)`,
`.vb-progress > span`, `.vb-spinner`, `.vb-hidden`.

UI language: German. Mobile-first, big touch targets, party look (dark,
pink→orange→yellow gradient). Must work on recent iOS Safari and Android
Chrome: `<video playsinline muted>`, no `ctx.filter`, no CSS filters on
captured output, iOS stops camera streams in background tabs.

## Testing

```bash
uv sync                      # deps incl. dev
uv run pytest                # unit/API tests (fast)
uv run pytest -m e2e         # browser tests: Playwright Chromium + fake camera
VB_E2E_BROWSER=firefox uv run pytest -m e2e   # the same in Firefox
tests/e2e/run_webkit.sh      # the same in WebKit (Docker)
uv run virtubooth gen-env > .env && set -a && . ./.env && set +a && uv run virtubooth serve --reload
```

Fixtures (`tests/conftest.py`): `settings`, `app`, `core`, `client`,
`make_client`, `guest(instagram=, fp_n=)` (consented guest client), `admin`
(logged-in client); helpers `jpeg()`, `scan()`, `accept_consent()`, headers
`JPEG`/`ORIGIN` (TestClient requests need `Origin: http://testserver` for
POST). Override the `extensions` fixture in a test module to load real
extensions, e.g. `return discover_extensions(["beer"])`.

E2E (`tests/e2e/conftest.py`): `live` (real server, `.url()`, `.entry()` =
QR URL, `.core`), `page`, `guest_page` (consent accepted), `admin_page`,
`accept_consent_in_browser()`; override `e2e_extensions`. `page.js_errors`
collects console errors (`track_errors(page)` for pages you make yourself).
`new_context(browser)` is a phone with a front and a back camera,
`new_context(browser, "desktop")` a 1280x800 PC with one 16:9 webcam showing a
test card (`window.__cameraRequests` lists the constraints asked for). Skip
markers for test tooling a browser lacks: `chromium_only` (CDP),
`needs_clipboard`, `firefox_only`. The CSP blocks string `wait_for_function`; use
`expect(locator)` instead. Chromium's fake camera shows a moving test
pattern; `VB_FAKE_VIDEO=file.y4m` swaps in your own clip.

## Ownership (parallel work, merge without conflicts)

| Area | Owns (may create/edit) |
|---|---|
| core | `virtubooth/*.py`, `virtubooth/static/core/`, `virtubooth/extensions/__init__.py`, `tests/conftest.py`, `tests/e2e/conftest.py`, `tests/*core*`, `pyproject.toml`, `uv.lock`, `docs/ARCHITECTURE.md` |
| beer | `virtubooth/extensions/beer/`, `tests/test_beer*.py`, `tests/e2e/test_beer*.py` |
| booth | `virtubooth/extensions/booth/`, `tests/test_booth*.py`, `tests/e2e/test_booth*.py` |
| admin | `virtubooth/admin/` (api.py, any new modules, static/), `tests/test_admin*.py`, `tests/e2e/test_admin*.py` |
| tools | `virtubooth/tools/`, `tests/test_tools*.py` |
| ops | `Dockerfile`, `.dockerignore`, `compose.yaml`, `.env.example`, `README.md`, `docs/DEPLOY.md` |
