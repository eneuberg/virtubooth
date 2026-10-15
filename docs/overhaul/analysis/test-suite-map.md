# Test suite map: virtubooth (`.worktrees/overhaul`)

> Historic: the suite before the overhaul. Its DOM-based e2e files (`tests/e2e/test_*_e2e.py` below) moved to `backend/tests/e2e_legacy/` in wave 1, were ported to `backend/tests/e2e/` (`guest/`, `activities/`, `admin/`) in wave 2, and were removed after the overhaul.

Repo root: `<repo>/.worktrees/overhaul`. I read every file under `tests/` in full, plus `pyproject.toml`, `Dockerfile`, `README.md` and `docs/ARCHITECTURE.md`. Nothing was modified and nothing was run.

## 0. Config and how tests are invoked

**`pyproject.toml` `[tool.pytest.ini_options]`:**
- `testpaths = ["tests"]`
- `norecursedirs = [".worktrees", ".venv", "data"]`
- `markers = ["e2e: browser end-to-end tests (playwright + chromium fake camera)"]` (no `--strict-markers`)
- `addopts = "-m 'not e2e'"`: a plain `pytest` runs only the unit/API tests; `-m e2e` on the command line overrides it.
- Dev dependencies: `pytest>=8`, `httpx2>=2.13` (imported as `import httpx2 as httpx` in the e2e tests), `playwright==1.63.0`.

**Invocations, as documented in `docs/ARCHITECTURE.md` "Testing" and `README.md` "Automated tests":**
```
uv run pytest                                  # unit/API
uv run playwright install chromium             # once (Linux: --with-deps)
uv run pytest -m e2e                           # Chromium + fake camera
VB_FAKE_VIDEO=clip.y4m uv run pytest -m e2e    # custom camera clip (.y4m/.mjpeg)
VB_E2E_BROWSER=firefox uv run pytest -m e2e    # Firefox
tests/e2e/run_webkit.sh [-k booth -x]          # WebKit in Docker
VB_BLOCKLISTS=.blocklists uv run pytest tests/test_core_blockers.py   # full filter lists (~60 MB)
```
- The Dockerfile is the production image only (uv build stage, then slim runtime with ffmpeg). It has nothing for tests; Docker is used for testing only through `run_webkit.sh`.
- `tests/__init__.py` and `tests/e2e/__init__.py` exist, so the e2e modules can do `from ..conftest import ...`.

**Environment variables that tests read:**

| Variable | Read by | Effect |
|---|---|---|
| `VB_E2E_BROWSER` | e2e conftest | `chromium` (default), `webkit` or `firefox` |
| `VB_FAKE_VIDEO` | e2e conftest | Chromium `--use-file-for-fake-video-capture=<file>` |
| `VB_SCREENSHOT_DIR` | conftest `shot()`; own `shot`/`snap` in beer, booth, desktop, upload-controls | optional screenshots |
| `VB_BOOTH_SCREENSHOTS` | booth e2e `test_screenshots`, long-party-name test | optional screenshots |
| `VB_BLOCKLISTS` | `test_core_blockers` | download/use the full filter lists |

`test_tools.py` has an autouse fixture that deletes every `VB_*` variable.

**Important for the rewrite:** neither runner has a frontend build step. Both `run_webkit.sh` and `uv run pytest -m e2e` serve the files on disk exactly as they are. A TypeScript build would need a build step before pytest, or a prebuilt dist placed where `virtubooth/pages.py` (`STATIC_DIR`, `ADMIN_STATIC`) and each extension's `static_dir` point. `run_webkit.sh` mounts the repo read-only and copies it.

---

## 1. Fixtures and helpers

### 1a. `tests/conftest.py` (unit/API; also imported by the e2e modules)

**Constants:**
- `PARTY_TOKEN = "test-party-token-0123456789"`
- `ADMIN_PASSWORD = "test-admin-password-123"`
- `SECRET_KEY = "test-secret-key-0123456789abcdef0123456789"`
- `BASE_URL = "http://testserver"`
- `ORIGIN = {"Origin": BASE_URL}`
- `JPEG = {"Content-Type": "image/jpeg", "Origin": BASE_URL}`

**Helpers (plain functions):**
- `jpeg(width=1080, height=1440, color=(200,120,40))`: solid PIL JPEG, quality 85.
- `png(200,200)`
- `fp(n=1)`: `{"hash": f"{n:064x}", "components": {"ua": "pytest", "screen": "390x844@3"}}`
- `scan(client, path="/")`: `GET {path}?t=TOKEN`, asserts 303 (the "QR scan").
- `accept_consent(client, instagram=None, fp_n=1)`: `POST /api/join {"accept": True, "version": "1", "instagram", "fp": fp(n)}` with Origin; asserts 200/201; returns the JSON.

**Fixtures (all function scope; no env vars set):**

| Fixture | What it does |
|---|---|
| `settings` | `Settings(party_token, admin_password, secret_key, data_dir=tmp_path/"data", party_name="Testparty", instagram_account="@testparty")` |
| `demo_extension` | `Extension(id="demo", title="Demo", emoji="🧪", tagline="Nur für Tests", static_dir=tmp/demo_static` (index.html + app.js), `upload=UploadPolicy(meta_keys={"mood"}, validate_meta=` raises `ValueError("Unbekannte Laune.")` unless mood ∈ {None, happy, sad}`)`, `on_upload=lambda ctx: {"count": ctx.core.repo.count_photos(ctx.extension.id)}`) |
| `extensions` | `[demo_extension]`; overridden in modules, e.g. `discover_extensions(["beer"])` |
| `app` | `create_app(settings, extensions=extensions)`; teardown `app.state.core.db.close()` |
| `core` | `app.state.core` |
| `make_client` | factory for `TestClient(app, base_url=BASE_URL, follow_redirects=False)`; calls `__enter__` (runs lifespan, binds the event bus); all closed at teardown |
| `client` | one `make_client()` |
| `guest` | factory `guest(instagram=None, fp_n=1)`: new client, `scan`, `accept_consent` (consented guest with its own cookie jar) |
| `admin` | client that did `POST /api/admin/login {"password": ADMIN_PASSWORD}` with Origin (asserts 200) |

No DOM coupling.

### 1b. `tests/e2e/conftest.py`

**Module constants:**
- `BROWSER_NAME = os.environ.get("VB_E2E_BROWSER", "chromium")`
- Skip markers:
  - `chromium_only`: defined but **unused**.
  - `needs_clipboard`: skips on WebKit.
  - `firefox_only`
- `FIREFOX_PREFS = {"media.navigator.streams.fake": True, "media.navigator.permission.disabled": True, "dom.events.testing.asyncClipboard": True}`
- Device profiles:

| Profile | Used for | Settings |
|---|---|---|
| `MOBILE` | Chromium phone | 390×844, `device_scale_factor` 2, `is_mobile`, `has_touch`, UA `Mozilla/5.0 (Linux; Android 14; Pixel 7) ... Chrome/140.0.0.0 Mobile Safari/537.36` |
| `FIREFOX` | Firefox phone | 390×844, `has_touch` (Firefox has no mobile emulation; `is_mobile` is popped) |
| `IPHONE` | WebKit phone | 390×844, dpr 3, `is_mobile`, `has_touch`, UA `iPhone OS 18_5 ... Version/18.5 Mobile/15E148 Safari/604.1` |
| `DESKTOP` | PC | `{"viewport": {1280, 800}}`, no touch, the browser's own UA |

**`PHONE_CAMERAS` init script** (Chromium and Firefox phones; not WebKit):
- Wraps `MediaDevices.prototype.getUserMedia` and remembers the requested `facingMode` (`exact`/`ideal`) per track in a WeakMap.
- Patches `MediaStreamTrack.prototype.getSettings` to report that `facingMode`.
- Wraps `enumerateDevices` to add a fake second `videoinput` (`deviceId:'back'`, label `'Back Camera'`) when only one exists.

**`WEBCAM` init script** (desktop contexts):
- The only camera is a 1280×720 canvas `captureStream(30)` test card:
  - red `#ff0000` background
  - blue `#1e46dc` column x 366..914 (the centred 3:4 region)
  - yellow `#ffdc00` 140 px square at (400,40)
  - a 2 px toggling pixel at (640,700) so frames keep coming
- `window.__cameraRequests` records every constraints object the page asks for.
- `facingMode.exact` other than `'user'` throws `DOMException('no back camera','OverconstrainedError')`.
- It calls the real gUM (so the permission flow runs), stops the real tracks and returns the test card.
- `enumerateDevices` is filtered to one `videoinput`.

**Fake camera per browser:**

| Browser | Launch | Camera |
|---|---|---|
| Chromium | `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` (+ `--use-file-for-fake-video-capture=$VB_FAKE_VIDEO`) | Built-in moving test pattern. **No Y4M generation anywhere in the suite**; a .y4m/.mjpeg is only user-supplied. |
| Firefox | `firefox_user_prefs=FIREFOX_PREFS` | `media.navigator.streams.fake` |
| WebKit | `playwright.webkit.launch()` with no args | WebKit's mock camera (front + back); no init script |

**Classes and functions:**
- `LiveServer(base_url, core)`: `.url(path)`, `.entry(path)` (the QR URL: path + `?t=`/`&t=` PARTY_TOKEN).
- `_free_port()`: binds 127.0.0.1:0.

**Fixtures:**

| Fixture | Scope | What it does |
|---|---|---|
| `e2e_extensions` | function | `None` = all discovered extensions (beer, booth); override per module |
| `e2e_settings` | function | `{}`; extra `Settings` fields |
| `live` | function | `Settings(party_token, admin_password, secret_key, data_dir=tmp_path/"data", party_name="E2E Party", **e2e_settings)`; `create_app(settings, extensions=e2e_extensions)`; `uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=_free_port(), log_level="warning"))` started in a daemon `threading.Thread(target=server.run)`; polls `server.started` for up to 10 s (else `RuntimeError("uvicorn did not start")`); yields `LiveServer("http://127.0.0.1:<port>", app.state.core)`; teardown `should_exit=True`, `join(5)`, `db.close()`. Same process, so tests can poke `live.core.repo` and monkeypatch modules. |
| `playwright` | session | `sync_playwright()` |
| `browser` | session | launched per the table above |
| `context` | function | `new_context(browser)` (phone); depends on `live` |
| `page` | function | `track_errors(context.new_page())` |
| `guest_page` | function | `page.goto(live.entry("/"))` then `accept_consent_in_browser(page)` |
| `admin_page` | function | new page in the same context; goes to `/admin/login` (needs a real page: WebKit styles JSON views inline, which the CSP blocks); runs `fetch('/api/admin/login', POST JSON {password})` via `page.evaluate`; asserts 200 |

**Helper functions:**
- `new_context(browser, device="phone"|"desktop", **options)`:
  - picks `DESKTOP`, or `IPHONE`/`FIREFOX`/`MOBILE` by browser, then merges `options` (viewport, user_agent, ...);
  - Firefox: pops `is_mobile`; others: `permissions=["camera"]`;
  - desktop: adds `WEBCAM`; phone (non-WebKit): adds `PHONE_CAMERAS`.
- `allow_clipboard(context)`: Chromium only, grants `clipboard-read`/`clipboard-write`.
- `track_errors(page)`: `page.js_errors` collects `pageerror` plus console `error` lines (`"{text} @ {url}"`).
  - Nearly every e2e test asserts `page.js_errors == []`. **CSP violations log console errors**, so the new frontend must be CSP-clean at runtime: no inline `<style>`/CSS-in-JS injection, no `style=` in markup, no eval.
- `shot(page, name, settle_ms=300)`: writes `$VB_SCREENSHOT_DIR/{BROWSER_NAME}_{name}.png`; drops "Refused to apply a stylesheet" errors (WebKit's screenshot injects a style).
- `settle_dialogs(page)`: awaits `document.getAnimations()` whose target is inside `.vb-scrim`. **DOM-coupled.**
- `accept_consent_in_browser(page, instagram="")`: waits for `get_by_test_id("join")`, fills `#vb-join-insta`, clicks `get_by_role("button", name="Alles klar")`, waits for `join` detached. **DOM-coupled.**

**Server CSP the e2e tests run under** (`virtubooth/security.py`): `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. `Permissions-Policy: camera=(self), microphone=(), geolocation=(), payment=(), usb=()`. The docs note that string `wait_for_function` is blocked by this CSP.

### 1c. `tests/e2e/run_webkit.sh`

- Image: `mcr.microsoft.com/playwright/python:v1.63.0-noble`.
- `docker run --rm --ipc=host -v "$ROOT":/src:ro`.
- Inside the container:
  - tars `/src` (excluding `.venv`, `.worktrees`, `data`, `.git`) into `/tmp/src`;
  - `pip install -q --root-user-action=ignore --break-system-packages -e . pytest httpx2 playwright==1.63.0`;
  - `VB_E2E_BROWSER=webkit python -m pytest -m e2e -q -p no:cacheprovider "$@"`.
- It relies on the image's preinstalled browsers and has no Node build step.

### 1d. Helpers and fixtures defined inside test modules (also DOM-coupled)

- **`test_admin_e2e.py`:**
  - `e2e_extensions`: a test extension `snap` (title "Schnappschuss", emoji 📷, `UploadPolicy(meta_keys={"mood"})`, `meta_labels={"mood": "Laune"}`, static index.html only).
  - `Guest`: an httpx2 client with the iPhone UA; `GET entry` → 303; `POST /api/join`; `upload()` posts `jpeg(800,1000)` to `/api/x/snap/upload`; `.user` resolved via `core.signer.unsign("uid", vb_uid)`.
  - `guests` factory; a duplicate `track_errors`; an `admin_page` override that re-wraps `track_errors`.
  - `card(page, id)` = `[data-photo-id="{id}"]`.
  - `real_errors` (drops "Failed to load resource"); `login_api`.
  - `desktop_page`: `browser.new_context(viewport=1280x800)`. Note: **not** `new_context()`, so no camera permission and no init script. Logged in via fetch.
  - `no_horizontal_scroll`: `scrollWidth <= innerWidth + 1`.
  - `_read_events` / `_wait_for` (SSE line readers); `scroll_to_bottom` (`window.scrollTo`).
- **`test_admin_a11y_e2e.py`:**
  - imports `card, desktop_page, e2e_extensions, guests` from `test_admin_e2e`;
  - `focused()` returns `activeElement.id || dataset.testid || tagName`;
  - `focus_inside(testid)`, `press_tab`, and the `CONTRAST` JS (WCAG ratio with alpha-composited ancestor backgrounds).
- **`test_admin_upload_controls_e2e.py`:**
  - the `snap` test extension with its own `SNAP_HTML`/`SNAP_JS` page built on the **core SDK** (see 3e);
  - `ApiGuest` (HTTP) / `api_guests`;
  - `BrowserGuest` (`new_context` phone; goes to `entry("/x/snap/")`; consents; waits for `go` enabled; reads the `vb_uid` cookie; `.hint` = `uploads-paused`; `.upload(state)` clicks `go` and waits for `out[data-state]`; `.recheck()` dispatches `visibilitychange` on `document`);
  - `browser_guests`; `chip_text`/`open_sheet`/`close_sheet`; `shot` (`upload-controls-{name}.png`); `real_errors` (drops "Failed to load resource" and "403").
- **`test_core_e2e.py`:** the `probe` test extension (`PROBE_HTML`/`PROBE_JS`), see 3a.
- **`test_core_ui_e2e.py`:**
  - `e2e_settings` = `{"instagram_account": "@e2e.party.account"}`;
  - `vb(page, expr)` dynamically imports `/static/core/vb.js` and evaluates with `vb` bound;
  - `network_noise` (drops "Failed to load resource", "ERR_", "NetworkError", "net::", "/api/");
  - `IN_SHEET_AT` JS; `contrast()`.
- **`test_beer_e2e.py`:** `open_beer`, `expect_success`, `beer_photos`, `stored_size`, `rate_limited(route, seconds)`, `uploads_paused`, `leaving_is_blocked` (dispatches a cancelable `beforeunload`, returns `defaultPrevented`), `add_beers` (inserts DB rows directly), `animations_done`, `inside(page, testid)` (fully in viewport ±1 px), `no_scrolling`, `shot`.
- **`test_booth_e2e.py`:**
  - `snap`, `open_booth` (waits for `booth[data-ready=1]`), `select`, `shoot`, `again`, `stored_images`;
  - `swipe` (mouse drag on `preview`); `touch_swipe` (CDP `Input.dispatchTouchEvent`; Chromium only);
  - `gray_error`, `border_diff`, `chip_offset`, `rate_limited`, `leaving_is_blocked`;
  - `kept_on_phone` (reads **IndexedDB `vb-booth` v1, store `outbox`, keyPath `id`**);
  - `Network` (route-based offline), `shoot_offline`, `network_errors_only`, `wait_kept`, `animations_done`, `inside`;
  - `NO_INDEXEDDB`, `DENY_CAMERA`.
- **`test_desktop_e2e.py`:** `desktop` (`new_context(browser, "desktop")`), `pc` (consented desktop guest), `on_screen`, `stored`, `is_yellow`/`is_blue`, `assert_portrait_crop` (centre 3:4 of the test card, mirrored, square not stretched), `screenshot_of`, `camera_requests` (`window.__cameraRequests`), `UPLOAD_JS` (raw fetch uploads to `/api/x/beer/upload` with `X-VB-Meta`).
- **`test_firefox_e2e.py`:** module-scoped `firefox(camera)` launches Firefox with `FIREFOX_PREFS | {"media.navigator.permission.disabled": False, "permissions.default.camera": 0|1|2}`; `SPY` init script (records gUM in `window.__cameraRequests` and passes through); `guest()`; `camera_state()` (`navigator.permissions.query({name:'camera'})`).

**Duplicated code:**
- `_collect_events` (in `test_admin_api` and `test_admin_upload_controls`)
- `track_errors` (conftest and `test_admin_e2e`)
- `rate_limited`, `uploads_paused`, `leaving_is_blocked`, `animations_done`, `inside` (beer and booth e2e)
- several `shot` variants

---

## 2. Per-file map

Counts are `def test_` functions, then collected cases after parametrization.

| File | Functions (cases) | Scope | Classification |
|---|---|---|---|
| `tests/test_admin_api.py` | 31 (61: `test_every_route_needs_admin` ×22, `test_mutations_need_same_origin` ×10) | admin API auth, CSRF, photos, bulk, users, bans, stats, Instagram, audit, extensions, events | pure API/unit (stays valid) |
| `tests/test_admin_pages.py` | 10 (25: ×3, ×3, ×4 html, ×4 html, ×6 js) | admin page gating plus static checks of admin HTML/JS sources | mixed (mostly frontend-source-coupled) |
| `tests/test_admin_upload_controls.py` | 17 (18) | per-guest pause, new-guest lock, stop-all, persistence, events | pure API/unit |
| `tests/test_beer.py` | 18 (27: meta ×8, assets ×3) | Beer Cam upload policy and stats; page/asset checks | mixed (14 API, 4 frontend-source) |
| `tests/test_booth.py` | 14 (31: filters ×10, meta ×9) | Fotobox meta, filter catalogue; page/source checks | mixed (9 API, 5 frontend-source) |
| `tests/test_core_access.py` | 38 (55: ×4, ×5, ×8, ×4) | gate/token, identity, consent, Instagram, CSRF, headers, settings, misc | pure API/unit (3 tests assert German text of server pages `gate.html`/`notfound.html`) |
| `tests/test_core_admin_auth.py` | 12 (12) | admin login, sessions, rate limits, gating redirects | pure API/unit |
| `tests/test_core_blockers.py` | 7 (7; 2 skip without `VB_BLOCKLISTS`) | URLs and UI elements vs ad/cookie filter lists | mixed (static analysis of frontend files) |
| `tests/test_core_db_migration.py` | 4 (4) | SQLite schema migration v1→v2 | pure unit (internals) |
| `tests/test_core_uploads.py` | 16 (16) | upload pipeline, media access, bans, tombstones, event bus | pure API/unit |
| `tests/test_tools.py` | 44 (50: scripts ×3, bad-options ×5; 6 need ffmpeg) | CLI timelapse/qr/export | pure unit |
| `tests/e2e/test_core_e2e.py` | 8 (8) | gate, consent→home, SDK camera+upload, blocked modules | e2e DOM-coupled (1 test is a pure filesystem check) |
| `tests/e2e/test_core_ui_e2e.py` | 19 (25: phones ×6, gate/404 ×2) | join dialog, Instagram dialog, chip, home errors, Retry-After, debug log, misc | e2e DOM-coupled |
| `tests/e2e/test_admin_e2e.py` | 23 (27: off-site next ×5) | login, live screen/SSE, manage, tabs, user page, bans, lightbox, scroll | e2e DOM-coupled (`test_event_stream` is HTTP-only) |
| `tests/e2e/test_admin_a11y_e2e.py` | 7 (7) | tabs roving tabindex, confirm/lightbox focus, names, contrast | e2e DOM-coupled |
| `tests/e2e/test_admin_upload_controls_e2e.py` | 4 (4) | Uploads chip/sheet, per-guest switch, guest hint | e2e DOM-coupled plus SDK-coupled |
| `tests/e2e/test_beer_e2e.py` | 20 (20) | Beer Cam flow, layout, errors, bans, shortcuts | e2e DOM-coupled |
| `tests/e2e/test_booth_e2e.py` | 34 (35: strip ×2; `test_screenshots` skipped without env) | Fotobox WebGL, filters, capture, countdown, outbox, leave sheet, layout | e2e DOM-coupled |
| `tests/e2e/test_desktop_e2e.py` | 5 (6: `test_screenshots` ×2, skipped without env) | PC with webcam: home, beer, booth, admin | e2e DOM-coupled |
| `tests/e2e/test_firefox_e2e.py` | 3 (8: 2 + 2 + 2×2; Firefox only) | real Firefox camera permission prompt/allow/block | e2e DOM-coupled |

**Totals:** unit 211 functions / 306 cases. e2e 123 functions / 140 cases.

### 2b. What each file asserts

**test_admin_api.py**
- `test_route_table_is_covered`: every route of `virtubooth.admin.api.router`, walked through FastAPI internals `route.original_router` / `include_context.prefix`, appears in `ROUTES` (22 entries).
- Every route returns 401 `{"error": "admin_required"}` for an anonymous client and for a consented guest.
- Every non-GET route without Origin returns 403 `bad_origin`; with `Origin: https://evil.example` it returns 403.
- Logout revokes API access.
- Invalid ids:
  - `/photos/{short|x*40|bad%20id!!!!!!!|..%2F..%2Fetc}` → 404/422;
  - `photos/a.b.c.d.e.f/hide` → 422;
  - `users/abc|0|-1` → 422;
  - `device-bans/NOTHEX` → 422;
  - `?user_id=abc`, `?extension=../x`, `?hidden=maybe`, `?before=nope` → 400;
  - `?before=<unknown id>` → `invalid_cursor`;
  - `limit=0|201` → 422.
- Unknown ids → 404 on get/hide/unhide/delete photo, user get/ban/unban, device-ban delete.
- Photos list: newest first; `total`, `next=None`; `extension`, `seq`; `thumb_url == "/media/{id}?thumb=1"`; `user.instagram`, `user.name`; `hidden False`.
- Pagination `limit` + `before`; `total` only on the first page; polling with `after`.
- Filters: `hidden=true|hidden|false|visible|all|""`, `user_id`, `extension`, empty params, `total` with filters.
- Hide/unhide: `changed`, `photo.hidden`, `hidden_reason=="admin"`, idempotent; audit `photo.hide`/`photo.unhide` with actor `admin:*`.
- A hidden photo is still served to the admin (`?thumb=1`, `?download=1`).
- Delete: `{"ok": True, "id"}`, files gone, `/media` 404, list excludes it, second delete 404, audit `photo.delete`, `seq` never reused.
- Bulk: `{"action", "changed", "unchanged", "missing"}` with dedupe; unhide/delete; files removed.
- Bulk validation: empty ids, >200 ids, unknown action, bad id, non-list → 422; 200 ids → 200.
- Users:
  - list `users[]` with `photo_count`, `next_offset`; `search=anna`, `search=%23<id>`; `banned=true|false`; `limit`/`offset`;
  - detail `user.instagram`, `user.fp_components.screen`, `user.consent_at`, `photos`, `fingerprints[0].fp_hash/current/users`, `sharing`.
- Shared fingerprint: `fingerprints[0].shared_with==1`, `users==[{id,name,instagram,banned,auto_banned}]`, `sharing`.
- Ban: `changed`, `fingerprint_banned`, `user.banned`, `ban_reason` whitespace-collapsed ("Spam Fotos"); photos hidden with `hidden_reason "ban"`; upload 403 `banned`; double ban `changed False`.
- Unban restores only ban-hidden photos; audit `user.ban`/`user.unban`.
- Fingerprint ban:
  - `device-bans` `bans[0]` has `fp_hash`, `reason`, `source_user_id`, `source_user_name`, `users`;
  - a new identity with the same fp gets `state:"banned"` and upload 403;
  - `DELETE device-bans/{hash}` lifts it; a newcomer gets `state:"ok"`; audit `fingerprint.ban`/`fingerprint.unban`.
- `{"fingerprint": true}` on a user without fp → 400 `no_fingerprint`, nothing half-done.
- Unban with `{"fingerprint": true}` → `fingerprints_unbanned`.
- Auto-banned identities: `ban_reason == queries.AUTO_BAN_REASON`; `auto_banned`, `auto_ban={"fp_hash","source_user_id","source_user_name"}` in users, detail, sharing and device-bans.
- Lifting an fp ban:
  - `users_unbanned` lists auto-banned ids (exact dict shape);
  - events `fingerprint.unbanned`, `user.unbanned` ×2;
  - manual bans and identities also on another banned fp stay banned;
  - `POST /api/identify {"fp"}` → `state:"banned"`.
- Unban with `fingerprint:false` keeps auto-bans; a one-tap unban of an auto-banned identity works.
- Ban `reason` longer than 200 chars → 422.
- Stats: `photos`, `visible`, `hidden`, `deleted`, `guests`, `banned`, `instagram`, `instagram_handles`, `uploaders`, `fingerprint_bans`, `extensions{demo:{photos,hidden}}`, `last_upload_at`; empty stats.
- Instagram: `handles[]` (`handle`, `photos`, `visible`, `hidden`, `users`, `last_upload_at`, `recent` = visible only, newest first); handles merged across `@anna`/`anna`; stats counts agree.
- Audit: paged `entries` (`action`, `target`, `actor`, `id`) with `next`; the last entry is `admin.login`.
- Extensions: `emoji`, `loaded`, `meta_labels`; an unloaded extension found in the DB shows `loaded False` (via raw SQL `core.db.all("UPDATE photos SET extension='oldext'")`).
- Events in order: `photo.hidden`, `photo.unhidden`, `fingerprint.banned`, `user.banned`, `user.unbanned`, `fingerprint.unbanned`, `photo.deleted` (with payload shapes). Bulk delete publishes one `photo.deleted` per photo.

**test_admin_pages.py** (paths: `virtubooth/admin/static/*.html`, `assets/*.js`)
- Expected files: html stems == {login, live, manage, user}; js ⊇ {admin.js, login.js, live.js, manage.js, user.js}; `assets/admin.css` exists.
- `/admin/{live,manage,user}` for anonymous and guest → 303 `Location: /admin/login?next=/admin/{page}`.
- For an admin → 200 text/html containing `src="/admin/assets/{page}.js"` and a CSP with `default-src 'self'`.
- `/admin/login?next=...` is public and contains `id="password"`.
- `/admin/assets/admin.js` → `text/javascript`, `admin.css` → `text/css` (no session needed); `/admin/assets/%2e%2e/api.py` and `nope.js` → 404.
- Each HTML file: no inline `<script>`, no `<style`, no `style=` attribute, no `on*=` handler, no external `src`/`href` (`https?:` or `//`); contains `<html lang="de">`.
- Every `src`/`href` starting `/admin/assets/` or `/static/core/` returns 200, and there must be at least one.
- Each JS file (comments stripped): no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval(`, `new Function`, `document.write`; no `style:` (an `h()` style prop); no `setAttribute('style'`.
- JS imports are only `./x` files inside `assets/` or exactly `/static/core/vb.js`.
- `live.js` must not contain `'DELETE'`, `'delete'`, `Löschen`, `/bulk`, `deletePhoto`, `confirmAndDelete`, `managementActions`, `photoTile`, and must contain `photo.deleted`. `live.html` has no `Löschen`/`delete`.

**test_admin_upload_controls.py** (`PAUSED_MSG = "Uploads sind für dich gerade pausiert. Die Gastgeber schalten sie bald wieder frei."`, `STOPPED_MSG = "Uploads sind gerade kurz gestoppt – gleich geht's weiter."`)
- Pausing a guest (`POST /api/admin/users/{id}/uploads {"paused"}`):
  - returns `changed`, `user.uploads_paused`, `uploads_paused_source == PAUSE_ADMIN`, `uploads_lock_period None`, `uploads_paused_at`;
  - upload returns exactly `{"error":"uploads_paused","message":PAUSED_MSG}`;
  - photos stay visible; not banned; `/api/extensions` 200; `PATCH /api/me` works and returns `user.uploads_paused`;
  - `identify` → `state ok`, and `set(user) == {"name","instagram","banned","uploads_paused"}` exactly;
  - idempotent; unpause clears the source;
  - audit `user.uploads_unpause`/`user.uploads_pause` with `details {"source": PAUSE_ADMIN}`, actor `admin:*`, target `user:{id}`.
- Validation: 404 unknown, 0 → 422, `{}` → 422, `paused:"x"` → 422.
- Ban wins over pause (`banned`); unban keeps the pause (`uploads_paused`).
- Users filter `paused=true|false|all`, combined with `banned=false`; `paused=maybe` → 400; listed `uploads_paused_source` is `PAUSE_ADMIN` or `PAUSE_NEW_GUEST_LOCK`.
- The photo's user ref shows `uploads_paused`.
- New-guest lock (`/api/admin/upload-pause`):
  - initial GET = `{"enabled":False,"since":None,"period":None,"by":None,"affected":0,"paused_total":0}`;
  - on: `enabled`, `changed`, `since`, `period==1`, `affected 0`; turning it on again → `changed False`;
  - a guest joining during the lock is paused with `uploads_lock_period 1` and `uploads_paused_at == created_at`; earlier guests are unaffected; `affected`/`paused_total` count it.
- Lift with `restore:true`:
  - `restored 1`, `kept 0`; a guest paused by hand stays paused;
  - audit `uploads.lock_off` `details {"period":1,"restore":True,"restored":1,"kept":0}` and `uploads.lock_on`.
- Lift with `restore:false`: `kept 2`, `paused_total 2`. A second period gives `period 2`; restore affects only that period.
- `{"enabled": false}` without `restore` → 400 `restore_required`; `{}` → 422.
- A rejoining known device is not paused (200).
- Stop-all (`/api/admin/upload-stop`):
  - initial GET `{"enabled":False,"since":None,"by":None}`;
  - on: `enabled`, `since`, `changed`, idempotent; upload → exactly `{"error":"uploads_stopped","message":STOPPED_MSG}`;
  - paused guests still get `uploads_paused`; identify `uploads_stopped` true/false;
  - off: `{enabled:False, since:None, by, changed:True}`; users and lock exactly as before; audit `uploads.stop`/`uploads.resume`.
- A stop while nobody is paused: joining still works and new guests are not paused.
- Validation: `enabled:"maybe"` / list body → 422.
- Both switches persist across `create_app` restarts.
- Events: `settings.upload_stop`(×2), `user.uploads_changed`(×2), `settings.upload_pause`, `user.created`, `settings.upload_pause`, `user.uploads_changed`, with payloads (`upload_stop.enabled`, `paused`, `users[0]`, `upload_pause.period`, `restored`/`kept`, `admin_view()`). Keep-paused publishes no user change.
- Switch routes need admin and same Origin (401/401/403 `bad_origin`).

**test_beer.py** (extensions = `discover_extensions(["beer"])`)
- `beer.extension`: id/title/emoji/order `("beer","Beer Cam","🍺",10)`; tagline <60 chars; `upload.max_side 1440`; `meta_keys {"vessel","facing"}`; `meta_labels {"vessel":"Gefäß","facing":"Kamera"}`; `static_dir/index.html` exists; discovered once.
- Upload returns `beer_number`, `total`, `photo.seq`, `width`/`height` 1080×1440; stored meta; 2 files.
- Stored image is 1080×1440.
- Invalid meta → 400 exactly `{"error":"invalid_meta","message":...}`:
  - "Unbekanntes Gefäß. Flasche oder Becher?" for no header, `{}`, `glass`, `BOTTLE`, `1`, `None`;
  - "Unbekannte Kamera." for `facing` `sideways`/`True`;
  - an unknown key is rejected.
- `facing: null` is dropped.
- 1600×2000 and 300×400 → `invalid_image`; 1440×1080 (wrong frame) → `invalid_image`.
- 401 `needs_consent`; 403 `banned`.
- `/api/x/beer/stats`: 404 `scan_qr` without access; with access only (no consent) → `{"total":0,"goal":1000000}`; counts only visible beers; numbers never reused (`beer_number` 4, `total` 2); other extensions ignored.
- Listed on home with `url "/x/beer/"`, `uploads True`.
- Frontend-coupled:
  - `/x/beer/` without access → 404 containing `data-testid="gate"`; with access, the HTML contains `beer.js` and `vb.css`;
  - `beer.js`, `shapes.js` (text/javascript) and `beer.css` (text/css) are served;
  - `index.html` is CSP-clean (HTMLParser) and contains test ids ⊇ {shutter, frame, vessel-bottle, vessel-cup, success-title, again};
  - no `*.js` uses `innerHTML` or an external URL (except `www.w3.org/2000/svg`);
  - every `$('id')` in `beer.js` exists as an id in `index.html`, and they include {goal-long, goal-short, retry, success-num}.

**test_booth.py** (`discover_extensions(["booth"])`)
- `/api/extensions` entry equals `{"id":"booth","title":"Fotobox","emoji":"📸","tagline":...,"url":"/x/booth/","uploads":True}`; `order 20`; `meta_labels {"filter":"Filter","facing":"Kamera"}`.
- Upload: `booth_number == photo.seq`, 1080×1440, meta stored.
- Every `booth.FILTERS` id is accepted (10: normal, bw, sepia, colorpop, party, emoji, neon, vhs, retro, comic).
- Invalid meta → "Unbekannter Filter." / "Unbekannte Kamera." (9 cases); missing or extra meta rejected; 1600×2133 → `invalid_image`; 401 `needs_consent`.
- Catalogue `static/filters.json`: ids == `list(booth.FILTERS)`; ⊇ {normal, bw, sepia, colorpop, retro, vhs, party, emoji}; first is `normal`; unique; `name` and `icon` non-blank; `FILTERS["bw"]=="Schwarz-Weiß"`.
- `booth.load_filters` raises `ValueError` on bad catalogues.
- Frontend-coupled:
  - `filters.js` ids parsed with regex `^\s{4}id: '([a-z][a-z0-9-]*)',$` must equal FILTERS;
  - `/x/booth/` is 404 before scan; after scan the HTML contains exactly `<script type="module" src="./booth.js"></script>` and booth.js, filters.js, renderer.js, overlays.js, outbox.js, booth.css and filters.json are served;
  - index.html is CSP-clean; JS has no `innerHTML`, no `ctx.filter`, no `https?://`;
  - `$('id')` lookups in `booth.js` ⊇ {back, outbox, upload-retry, upload-home} and exist in index.html;
  - `outbox.js` functions `keep`, `forget`, `kept` (split on `export async function NAME(`) contain `try {` and `catch`.

**test_core_access.py**
- Without the token, `/`, `/x/demo/`, `/x/demo/app.js`, `/nope`, `/x/unknown/` → 404 with "Scan den QR-Code". With access, `/nope` → 404 "Hier ist nichts".
- Wrong token → gate, no `vb_access` cookie.
- The token sets `vb_access` (HttpOnly, SameSite=Lax), 303 strips `t` and keeps other params (`/x/demo/?debug=1`); assets get the right type.
- Rotating `party_token` invalidates access.
- API without access → 404 `scan_qr` (`/api/identify`, `/api/extensions`).
- Identify → consent flow: `state needs_consent`, `consent.version "1"`, `consent.paragraphs` mention `@testparty`; join → 201, `state ok`, `instagram` normalized `party.animal`, `name` ends `#1`, `vb_uid` cookie; identify `ok`; `fp_hash` stored.
- Join: `accept:false` → 422; no fp → 422 and no user created; version "0" → 409 `consent_outdated`; idempotent for a known device.
- `uid_token` restores identity when the cookie is lost (sets `vb_uid`); forged token or cookie → `needs_consent`.
- `normalize_instagram`:
  - normalizes `@Foo.Bar`, a profile URL, blanks;
  - rejects garbage with `ApiError`;
  - errors say what is wrong (`code=="invalid_instagram"`; messages contain "höchstens 30 Zeichen, deiner hat 31", "deiner hat 40", "keine Umlaute", "keine Akzente", "keine Leerzeichen", "Zwei Punkte", "nur Buchstaben (a bis z), Zahlen, Punkt und Unterstrich").
- Second-tab join: `already_joined`, `instagram_kept`; a missing handle is added; an existing handle is kept; the handle is validated (400 `invalid_instagram`); a banned device cannot set a handle (`state banned`).
- `PATCH /api/me` sets, clears (None) or rejects (400) the handle.
- New-user rate limit → 429 with `retry-after`.
- CSRF: no Origin 403, foreign Origin 403 `bad_origin`, same-origin `Referer` OK.
- `security.origin_allowed`: host:port normalization, `allowed_origins`, `null`, suffix attack.
- Headers: CSP has `default-src 'self'`; `nosniff`; `no-referrer`; `camera=(self)`; `Cache-Control: no-store` on the API.
- Static traversal → 404 (4 paths, incl. a dotfile).
- `/api/extensions` has `party_name` and `extensions[0].id/url`.
- `Settings` validation and `Settings.from_env` (`VB_EXTENSIONS`, `VB_UPLOADS_PER_USER_PER_MIN`).
- `pseudonym` unique and grammatical; `AccessLogFilter` masks `t=***` and skips `/healthz`; `HEAD /healthz` 200.
- `discover_extensions` order (default `["beer","booth"]`; unknown → `ConfigError`).
- `//evil.example/?t=` → `Location /evil.example/`.
- JSON body cap: 413 for a 200 KB body, 411 for chunked.
- Per-device API budget (429 for the noisy device, others fine).
- HTTPS: HSTS `max-age=31536000` plus Secure cookies; plain HTTP has neither; `public_base_url` https → Secure.

**test_core_admin_auth.py**
- Session `{"authenticated":bool}`; login sets `vb_admin` (HttpOnly, SameSite=Strict); logout works.
- A stolen cookie dies on logout.
- 5 wrong passwords → 401 `wrong_password`, then even the right password gets 429; audit `admin.login_failed`.
- Global lockout across IPs (`[401,401,429,429]`) never locks out the real password.
- A password change ends sessions.
- Login needs same Origin.
- `/admin/live` → `/admin/login?next=/admin/live`; `/admin` → `/admin/live`; `/admin/user?id=5` → `next=/admin/user%3Fid%3D5`.
- `/api/admin/session` is public.
- A guest's forged `vb_admin` (43 or 500 chars) is not authenticated.
- `Limits.from_settings` / `.reset()`.
- An admin is exempt from the shared `api_ip` budget; anonymous callers get 429.

**test_core_blockers.py**: see section 5.

**test_core_db_migration.py**
- A fresh DB has `user_version == SCHEMA_VERSION == 2`, the `uploads_*` columns, and an empty `settings` table.
- A v1 DB (built from `SCHEMA` with 10 rows across users, user_fingerprints, fingerprint_bans, photos, admin_sessions, audit_log) upgrades in place: rows identical; repo reads work; new columns empty; pause/lock/stop work; reopening is idempotent.
- A failed migration step (monkeypatched `dbmod.MIGRATIONS = ((1, SCHEMA), (2, broken))`) rolls back to `user_version 1` with no partial column; the real migration runs afterwards.
- A newer DB version is left alone.

**test_core_uploads.py**
- Happy path: `seq`, on_upload extras (`count`), meta stored, files and thumbs, timestamped names sort.
- Re-encode strips EXIF and trailing garbage.
- Rejections: `image/png` content-type → 415; png body / garbage / >max_side / <min_side → `invalid_image`; unknown meta key → `invalid_meta`; `validate_meta` message "Unbekannte Laune."; non-JSON header → 400; empty body → 400/422; unknown extension → 404.
- `exact_size` policy message contains "1080×1440".
- Too large → 413, including a chunked body with a lying length.
- Access → consent → ban gating (`scan_qr`, 401, 403 `banned`).
- Per-user rate limit → 429 with `retry-after >= 1`, others unaffected.
- `/media` access: owner OK, stranger/anonymous 404, admin OK; `download=1` gives `attachment`; traversal 404; deleted 404; thumb is `image/jpeg`.
- Repo: ban/unban hides and restores only ban-hidden photos; fp ban catches a new identity; delete keeps a tombstone and the sequence; `PhotoQuery` pagination before/after.
- Upload publishes `user.created`/`photo.created`.
- `EventBus` drops a stalled subscriber.
- `format_sse` gives exactly `'id: 3\nevent: photo.created\ndata: {"a": 1}\n\n'`.
- Junk uploads don't use up shared IP budgets.

**test_tools.py**: `_common` (`resolve_data_dir`, `open_repo`/`ToolError`, `iter_photos`, `scratch_parent`), the `python -m virtubooth.tools.{timelapse,qr,export} --help` scripts, timelapse (options/filters/size/letterbox, real ffmpeg videos, crossfade, 2000 photos, dry run, missing files, bad options, missing binary/DB, staging under the data dir), qr (URLs, PNG/SVG/sheet, error level H, ordering, env defaults, token never printed, missing token/base URL, http warning), export (tar layout, CSVs with BOM, `--no-hidden`, `--no-db`, consistent WAL snapshot, missing files, CSV formula escaping). Frontend-independent.

---

## 3. E2E contract: DOM selectors, hooks and behaviours, by file

Notation: `tid:` = `get_by_test_id` / `[data-testid=...]`. Where a test id comes from is noted where useful (from a grep of the current frontend).

### 3a. test_core_e2e.py

**Selectors:**
- `tid:gate` (static/core/gate.html) plus text "Scan den QR-Code"
- `tid:join`, `#vb-join-insta`, button "Alles klar" (via the conftest helper)
- `tid:tile-probe` (home.js renders `tile-${ext.id}`)
- `tid:user-chip` (vb.js)
- `#vb-insta-edit`, button "Speichern"
- `tid:load-failed` (loader.js, a classic script) with text "Blocker"
- `#out` (probe page) with text "done" and `dataset.seq`

**Hooks:**
- Probe extension page (test-owned): `<link href="/static/core/vb.css">`, `.vb-stage`, `<video id="v">`, and `import { boot, openCamera, captureFrame, canvasToJpeg, uploadJpeg } from '/static/core/vb.js'`.
  - SDK contract: `openCamera(video, {facing:'environment'})` returns `{video,...}`; `captureFrame(video,1080,1440)` returns a canvas; `canvasToJpeg(canvas,0.85)` returns a Blob; `uploadJpeg('probe', blob, {meta:{kind:'test'}})` returns `{photo:{seq}}`.
- `page.route("**/static/core/device.js", abort "blockedbyclient")` and `page.route("**/static/core/vb.js", abort)`. These module URLs are part of the contract.
- An init script wraps `getUserMedia` into `window.__cameraRequests`.

**Behaviours:**
- The token is stripped from the URL (`page.url == /`).
- After consent: the chip shows the handle; the DB user has a 64-hex `fp_hash`; a reload shows no join dialog and keeps the same user.
- A capture+upload from the fake camera stores 1080×1440 with meta `{"kind":"test"}`.
- On OverconstrainedError the camera retries:
  - first request `video.width == {"ideal": 1920}`;
  - retry exactly `{"audio": False, "video": {"facingMode": "environment"}}`.
- Editing Instagram from the chip saves.
- If `device.js` is blocked, consent still works with `fp_components.fallback == True` and a 64-hex hash.
- If `vb.js` is blocked, the `load-failed` hint mentions "Blocker".
- `test_static_file_names_avoid_blocker_keywords`: see section 5 (filesystem only).

### 3b. test_core_ui_e2e.py

`e2e_settings` = `instagram_account "@e2e.party.account"`.

**Roles and names:**
- `dialog` "Willkommen bei E2E Party" (the consent title includes the party name)
- `dialog` "Dein Instagram"
- buttons "Alles klar", "Speichern", "Abbrechen", "Neu laden"
- `status` (toast) filtered by "Du bist schon dabei als"

**Test ids:** `join`, `user-chip`, `fatal`, `debug-toggle`.

**Ids and classes:**
- `#vb-join-insta` (`maxlength="31"`), `#vb-insta-edit` (`maxlength="31"`), `#party-name`
- `.vb-sheet-body`, the class `vb-sheet--more` on the dialog element (regex `\bvb-sheet--more\b`)
- `.vb-field-error`, `.vb-chip-text`, `.home-tile`, `.vb-debug-log`, `.vb-debug`, `.vb-notice-emoji`, `.vb-scrim` (settle_dialogs)
- `button[type=submit]` inside `[data-testid=join]`
- a created `button.vb-btn.vb-btn--danger` (core CSS class contract)

**JS module hooks:**
- `import('/static/core/vb.js')` exports `sheetOpen()`, `uploadJpeg(ext, blob)`, `api(path)`, `fatal(err)` (returns an element with `.textContent`).
- `ApiError` fields: `.name=="ApiError"`, `.status`, `.retryAfter`, `.message`.
- `import('/static/core/camera.js').cameraErrorMessage({name})`.

**Storage:** sessionStorage `vb_debug` and `vb_debug_folded` (behaviour only: the log stays folded across a reload in the same session; keys are not read directly).

**Behaviours:**
- Small phones (375×548, 360×560, 320×568, 375×629, 360×640, 390×844): the "Alles klar" button is fully on screen, and the topmost element at its centre is that submit button inside `join`. If `.vb-sheet-body` overflows, the dialog has `vb-sheet--more`. A click there joins (1 user, no JS errors).
- At 320×460 the dialog has `vb-sheet--more`; scrolling `.vb-sheet-body` to the end removes it.
- Before joining, `#party-name` text is "E2E Party" and the page `<title>` is "E2E Party".
- Join dialog keyboard:
  - the dialog itself is focused first;
  - Tab cycles field → "Alles klar" → field; Shift+Tab goes back;
  - `vb.sheetOpen()` is true while open;
  - Escape and a click at (5,5) don't dismiss it;
  - Enter in the field submits; then `sheetOpen()` is false.
- Handle errors: "jürgen" → `.vb-field-error` contains "keine Umlaute" and the field keeps focus; "@party.anna" joins and is stored as `party.anna`.
- Pasting `https://www.instagram.com/party.anna/?igsh=abcdefghijklmnop` into the field gives value `@party.anna` (Chromium/Firefox only).
- Two tabs, first without a handle, second with `@tab.b`: a status toast "Du bist schon dabei als ... @tab.b"; chip text exactly `🙂 @tab.b`; one user with `tab.b`.
- Two tabs with different handles: the toast contains "@tab.a" and "Tipp auf deinen Namen"; the DB keeps `tab.a`.
- Instagram dialog:
  - Enter on the focused chip opens it; the field is focused; Tab order Speichern → Abbrechen → field; Shift+Tab → Abbrechen;
  - `sheetOpen()` true; Escape closes and returns focus to the chip;
  - a scrim click closes it;
  - "@müller" → `.vb-field-error` "keine Umlaute" and focus stays;
  - typing "@"+40×x is capped to "@"+30×x;
  - "@neu.name" saves; chip shows `🙂 @neu.name`.
- At 320×640:
  - chip text `🙂 {pseudonym without " #N"} · Insta?` and `title` = full name;
  - with a 30-char handle: `🙂 @aaaa…`; chip right edge ≤ 320−16+1; `.vb-chip-text` overflows with `text-overflow: ellipsis`; no page horizontal overflow.
- `/api/identify` blocked: `fatal` contains "Keine Antwort" and "Blocker", not "Keine Verbindung"; button "Neu laden" focused; after unroute, reload → consent → `.home-tile` visible and `fatal` gone.
- `navigator.onLine=false` plus an aborted identify: `fatal` contains "Keine Verbindung" and has a "Neu laden" button.
- `/api/extensions` 429 with `Retry-After: 12`: `fatal` contains "Langsam! Zu viele Anfragen. Warte kurz (in 12 s nochmal)."
- SDK with a 429 and `Retry-After: 120`: `uploadJpeg` rejects with `["ApiError", 429, 120, "Langsam! Zu viele Anfragen. Warte kurz (in 2 min nochmal)."]`; `api()` gives `[120, same message]`.
- `fatal(TypeError)` does not show the raw message and includes "Neu laden"; a second `fatal` doesn't stack (count 1).
- `?debug=1`:
  - `.vb-debug-log` is visible, contains "debug on" and sits at the top (y<10);
  - taps pass through (the element at its centre isn't inside `.vb-debug`);
  - `debug-toggle` folds it (`aria-expanded="false"`); still folded after a reload; clicking again shows it.
- In-app browser UA (`... Instagram 390.0.0.27.81 ...`): `cameraErrorMessage` for NotAllowedError/SecurityError/NotFoundError contains "Safari oder Chrome" and not "aA"/"Schloss". With a normal UA, NotAllowedError contains "verweigert" and not "Safari oder Chrome".
- `.vb-btn--danger` contrast ≥ 4.5.
- Gate `/` and 404 `/nowhere`: `.vb-notice-emoji` visible with font-size ≥ 60px.

### 3c. test_admin_e2e.py

`snap` extension; guests over HTTP.

**Test ids:**
- Login: `login-error` (login.html)
- Live: `conn` with `data-state` ∈ {`live`, `reconnecting`} (live/manage/user.html); `stat-photos`, `stat-guests`, `stat-hidden`, `empty` (live.html)
- Cards: `photo-card` (live.js), `photo-tile` (admin.js); `user-link` (href `/admin/user?id=N`); `status`; `thumb`
- Lightbox: `lightbox`, `lightbox-close`, `download` (href `/media/{id}?download=1`), `copy-handle`
- Manage: `delete`, `confirm`, `confirm-cancel`, `confirm-ok` (admin.js); `photo-total`; `select`, `select-all`, `bulk-count`, `bulk-hide`, `bulk-delete`, `bulkbar`; `filter-status`, `filter-user` (a native `<select>`, `select_option(str(user.id))`); `guest-row`, `guest-search`; `insta-row`, `insta-count`, `copy-all-handles`; `banned-user-row`, `banned-users`, `fp-ban-row`, `unban-fp`, `unban-user`, `auto-ban`, `fp-auto-note`; `audit`
- User page: `user-name`, `user-insta`, `user-status`, `device`, `fp-shared`, `fingerprints` (contains a `link`), `fp-warning`, `ban-reason`, `ban-fp` (checkbox), `ban`, `ban-panel`, `unban-fp` (checkbox here, `id="unban-fp"`), `unban`, `auto-ban-note`
- Note: `unban-fp` is a button on the manage page but a checkbox on the user page.

**Other selectors:**
- `[data-photo-id="<id>"]` on cards and tiles; `[data-testid=photo-card]`.first has `data-photo-id`
- `[data-testid*=delete]` must not exist on live
- class `is-hidden` on a hidden card
- `#password`, `#count-instagram` (text plus `title` attribute), `label[for=unban-fp]`, `.vb-toast` (`.last`)

**Roles, names and texts:**
- buttons "Anmelden", "Abmelden", "🙈 Runternehmen", "👁 Wieder zeigen"; in `filter-status`: "Versteckt", "Alle"
- tabs "📸 Fotos" (`aria-selected="true"`), "📷 Instagram", "🚫 Sperren", "📜 Protokoll"
- `get_by_text("Löschen")` must have count 0 on live
- "Gast nicht gefunden.", "Kein Gast ausgewählt."

**Hooks:**
- `fetch('/api/admin/login')`, `fetch('/api/admin/photos/'+id, {method:'DELETE'})`
- `page.route("**/api/admin/events", abort)`
- `window.scrollTo`, `navigator.clipboard.readText()`
- `monkeypatch admin_api.SESSION_RECHECK_SECONDS = 0`
- `live.core.limits.upload_user = RateLimiter(1000, 60)`

**Behaviours:**
- Login:
  - `/admin/manage` → `/admin/login?next=/admin/manage`; a wrong password shows exactly "Falsches Passwort."; the correct one goes to `/admin/manage` with the Fotos tab selected;
  - already logged in, `/admin/login?next=/admin/live` forwards immediately;
  - `next` values `https://evil.example/`, `//evil.example/admin/live`, `/admin/../x`, `/admin/Live`, `javascript:alert(1)` all land on `/admin/live`;
  - `/admin/user?id=1` → login `next=/admin/user%3Fid%3D1` → back to `/admin/user?id=1`;
  - after 5 wrong passwords, `login-error` contains "Zu viele Anfragen";
  - "Abmelden" → `/admin/login`; `/admin/live` then redirects to login.
- Live screen:
  - card visible; `conn` `data-state=live`; stats 1/1;
  - a new upload arrives via SSE and is the first card; stat 2;
  - card text "📷 Schnappschuss #2", "@anna.party"; `user-link` href; `status` "✓ Sichtbar";
  - "🙈 Runternehmen" → "🙈 Versteckt", class `is-hidden`, DB hidden, `stat-hidden` 1; "👁 Wieder zeigen" → "✓ Sichtbar";
  - no "Löschen" or delete test ids;
  - thumb → lightbox with "Schnappschuss #1"; the lightbox "🙈 Runternehmen" → "Versteckt"; `lightbox-close` closes;
  - no horizontal scroll.
- Two live screens stay in sync; a DELETE elsewhere removes the card.
- With the SSE route aborted: `empty` visible, `conn` `reconnecting`, a new upload appears within 12 s (polling).
- `user-link` → user page with `user-name` "🙂 {name}", `user-insta` "@clara.k", and the card present.
- Manage delete (desktop):
  - `photo-total` "2 Fotos"; `delete` → `confirm` contains "endgültig löschen?"; cancel keeps it;
  - ok removes it; `photo-total` "1 Foto"; files deleted.
- Bulk and filters:
  - `select` click plus Shift+click selects a range (2, not 3); `bulk-count` "2 ausgewählt"; `bulk-hide` → `bulkbar` hidden, statuses hidden;
  - `filter-status` "Versteckt" → 2 tiles and the URL contains `status=hidden`; `filter-user` → 1; "Alle" → 2;
  - `select-all` → "2 ausgewählt"; `bulk-delete` cancel keeps the selection; `confirm` "2 Fotos endgültig löschen?"; ok → 0 tiles.
- Lightbox download/copy (not WebKit):
  - `download` href; `copy-handle` → `.vb-toast` "Kopiert: @dj.dennis" and clipboard "@dj.dennis";
  - the download's suggested filename is `snap-00001.jpg`; Escape closes.
- Tabs:
  - `?tab=gaeste` shows 2 guest rows; search "ben" → 1;
  - Instagram tab: 2 insta rows, `#count-instagram` "2", `insta-count` "2 Handles · 2 Gäste"; `copy-all-handles` → clipboard "@ben" (banned left out);
  - Sperren: 1 banned row, 1 fp row; `unban-fp` and `unban-user` remove them;
  - Protokoll: `audit` contains "Gast entsperrt" and "Fingerprint entsperrt".
- `?tab=instagram`: 2 rows, "2 Handles · 3 Gäste"; `#count-instagram` "2" with `title` "2 Handles · 3 Gäste".
- User page ban/unban:
  - `user-status` "✓ Aktiv"; 2 tiles; `device` "iPhone · iOS 18.5 · Safari 18.5";
  - `fp-shared` "1 anderes Gerät teilt diesen Fingerprint:"; the link to the twin; `fp-warning` contains "gleiche Handymodelle";
  - ban with reason "Spam" and `ban-fp` → `confirm` contains "Zusätzlich wird der Fingerprint gesperrt."; ok → "🚫 GESPERRT", `ban-panel` "Spam", photo statuses "🙈 Versteckt (Sperre)";
  - the guest's upload is 403; the known twin can still upload; a new identity on that fp is banned;
  - `unban-fp` plus `unban` → "✓ Aktiv", "✓ Sichtbar"; no fp bans left.
- Auto-banned devices:
  - Sperren tab (phone) shows 3 rows and 2 `auto-ban` badges; the row has "Automatisch gesperrt" and "gesperrt über {troll}"; `fp-auto-note` "2 Geräte sind nur wegen";
  - user page `label[for=unban-fp]` "Entsperrt auch 2 weitere Geräte"; unban → toast exactly "Gast und Fingerprint entsperrt · 2 weitere Geräte entsperrt";
  - the other open Sperren tab empties live via events.
- One-tap unban of an auto-banned device:
  - `user-status` "🚫 AUTO-GESPERRT"; `auto-ban-note` has "Automatisch gesperrt", "gesperrt über …", "vielleicht ist das jemand anderes";
  - `fingerprints` contains "{other} 🚫 auto"; `unban` → "✓ Aktiv" and the fp stays banned;
  - Sperren row `auto-ban` "AUTO-GESPERRT"; `unban-user` removes it; `unban-fp` → last toast "Fingerprint entsperrt".
- Delete from the user page on a phone; no sideways scroll.
- Unknown user texts (see above).
- No sideways scroll on a phone for live/manage/gaeste/instagram/user with a 30-char handle; `conn` live on each.
- `test_event_stream` (HTTP-only):
  - anonymous → 401; `text/event-stream`; a `retry:` line;
  - after a hide: `event: photo.hidden` then `data:` with the id and `"hidden": true`;
  - after logout, the next event ends the stream.
- Browser Back closes the lightbox, and the URL stays `/admin/live`.
- Infinite scroll: live shows 30 cards then 55 (oldest last); manage shows 48 tiles then 55; `photo-total` "55 Fotos".

### 3d. test_admin_a11y_e2e.py

**Ids:** `#tab-{fotos,gaeste,instagram,sperren,protokoll}` (with `tabindex` and `aria-selected`), `#panel-{...}`; `main` (`.inert`).

**Test ids:** `ban`, `confirm`, `confirm-cancel`, `confirm-ok`, `user-status`, `ban-panel` (contains a `heading`), `thumb`, `lightbox`, `lightbox-close`, `toggle`, `lightbox-delete`, `delete`, `status`, `auto-ban`, `banned-user-row`.

**Classes:** `.adm-badge--ban:not(.adm-badge--auto)`.

**Roles:**
- `alertdialog` "{name} sperren?" with `aria-modal="true"` and an accessible description matching "sichtbare Foto wird versteckt"
- `dialog` "Foto 📷 Schnappschuss #2" / "#1" with `aria-modal`
- `combobox` "Aktivität" and "Gast"
- `tab` "📸 Fotos"

**Behaviours:**
- Tabs:
  - roving tabindex `["0","-1","-1","-1","-1"]`;
  - ArrowRight moves focus and selection, shows `#panel-gaeste`, hides `#panel-fotos`, URL `tab=gaeste`, tabindex follows;
  - End → protokoll; ArrowRight wraps to fotos; ArrowLeft → protokoll; Home → fotos;
  - Tab moves focus to `#panel-fotos`.
- Confirm dialog:
  - Enter on `ban` opens it; focus on `confirm-cancel`; Tab/Shift+Tab ×4 stay inside; `main.inert` true;
  - Escape closes, focus back on `ban`, `inert` false, not banned;
  - confirming → "🚫 GESPERRT" and focus on the `ban-panel` heading.
- Lightbox:
  - focus starts on `lightbox-close`; Tab ×12 and Shift+Tab stay inside;
  - Enter on `toggle` → "👁 Wieder zeigen" and keeps focus;
  - ArrowRight → the older photo's dialog; Escape → focus on the thumb of the last shown photo.
- Delete from the lightbox:
  - `confirm-ok` is on top (elementFromPoint); the lightbox closes, the card is removed;
  - after 300 ms the URL is exactly `/admin/manage` (one history step); focus on the next photo's thumb.
- Deleting a tile moves focus to the neighbour's thumb.
- On a phone the filter selects are named "Aktivität" and "Gast".
- Contrast ≥ 4.5 for: hidden `status`, `toggle` button, tile `delete`, `auto-ban` badge, `.adm-badge--ban:not(.adm-badge--auto)`, and status "🙈 Versteckt (Sperre)".

### 3e. test_admin_upload_controls_e2e.py

**Test page** (SNAP_HTML/SNAP_JS, test-owned):
- `<main class="vb-page"><div id="chip">`, button `#go` / `tid:go` (classes `vb-btn vb-btn--primary vb-btn--big`), `<p id="out" data-testid="out">`
- `import { boot, canvasToJpeg, mountUserChip, uploadJpeg } from '/static/core/vb.js'`
- On error: `out.dataset.state = err.code`, `out.textContent = err.message`; on success: `Hochgeladen #${res.photo.seq}`.

**Admin test ids:**
- `uploads-chip`, `uploads-chip-text`, `uploads-sheet`, `uploads-status`, `uploads-close`
- `upload-pause-state` and `upload-stop-state` (built as `upload-${name}-state` in uploadcontrols.js)
- `pause-end-text`, `pause-end-keep`, `pause-end-restore`, `uploads-paused-list`
- `paused-badge`, `guest-row`, `conn`
- `guest-uploads`, `guest-uploads-status`, `guest-uploads-source`

**Guest test ids (from core vb.js):** `uploads-paused` (the hint), `uploads-paused-info`.

**Roles:**
- `switch` "Neue Gäste pausieren" and "Alle Uploads stoppen" (`aria-checked`)
- buttons "Alles klar", "⏸ Uploads pausieren", "▶ Uploads erlauben", "⏸ Pausiert" (`aria-pressed="true"`), "Alle" (exact)

**Other hooks:** document `visibilitychange` triggers a recheck; `vb_uid` cookie. `SINCE = r"seit \d\d:\d\d"`.

**Behaviours:**
- Pause new guests, then restore:
  - chip "🟢 Uploads laufen"; sheet status "🟢 Uploads laufen"; switch `aria-checked` false → true;
  - `upload-pause-state` "Neue Gäste können seit HH:MM nichts hochladen · 0 betroffen"; chip "⏸ Neue Gäste pausiert seit HH:MM · 0 betroffen";
  - a new browser guest sees the hint exactly "⏸ Uploads sind gerade pausiert"; clicking it shows `uploads-paused-info` with "Uploads sind für dich pausiert" and "Instagram-Namen"; "Alles klar" closes it;
  - the upload's `out` gets `data-state uploads_paused` and text PAUSED_MSG; the hint stays;
  - the known API guest gets 201; the admin chip counts live "· 1 betroffen";
  - toggling off: `pause-end-text` "1 Gast ist beigetreten"; `pause-end-keep` exactly "Nur ab jetzt wieder erlauben – der eine bleibt pausiert"; `pause-end-restore` exactly "▶ Den 1 in der Pause beigetretenen Gast wieder freischalten";
  - click → text "▶ 1 Gast wieder freigeschaltet"; status/chip "🟢 Uploads laufen";
  - the guest uploads "Hochgeladen #2" and the hint disappears.
- Pause new guests, then keep (from `/admin/manage?tab=gaeste`):
  - status contains "⏸ Neue Gäste pausiert"; the new guest's row `paused-badge` "⏸ Uploads pausiert" (live);
  - clicking the row opens the user page: `guest-uploads-status` "⏸ Uploads pausiert", `guest-uploads-source` "automatisch: neue Gäste pausiert seit HH:MM"; then Back;
  - keep → text "▶ Neue Gäste können wieder hochladen – 1 bleibt pausiert"; `uploads-paused-list` "⏸ 1 Gast pausiert · ansehen ›";
  - the guest is still refused; a later guest gets 201;
  - the link → `?tab=gaeste` with "⏸ Pausiert" pressed and 1 row with a badge; "Alle" → 2.
- Pause one guest from the user page:
  - "✓ Darf hochladen"; "⏸ Uploads pausieren" → "⏸ Uploads pausiert", source "manuell pausiert · seit HH:MM"; source `admin`; the photo stays visible;
  - the guest's upload is refused and the hint appears;
  - "▶ Uploads erlauben" → "✓ Darf hochladen";
  - `visibilitychange` → the hint goes, "Uploads sind wieder frei 🎉" appears; upload "Hochgeladen #2".
- Stop all, then back:
  - two admin screens show the chip "⏸ Neue Gäste pausiert seit … · 0 betroffen";
  - the stop switch → `aria-checked` true; `upload-stop-state` "Gestoppt seit HH:MM"; status "⏹ Alle Uploads gestoppt seit HH:MM · ⏸ neue Gäste pausiert"; the other screen's chip "⏹ Alle Uploads gestoppt seit HH:MM";
  - guest `out` `uploads_stopped` with STOPPED_MSG; hint "⏹ Uploads kurz gestoppt", also after a reload; the paused API guest gets 403;
  - unstopping restores the chip; pause and lock are untouched;
  - `visibilitychange` → hint gone → "Hochgeladen #1".

### 3f. test_beer_e2e.py

**Test ids:**
- `shutter`, `success`, `success-title`, `success-count`, `success-togo`, `again`, `home`
- `overlay` (`data-vessel` ∈ {bottle, cup}; shapes.js), `overlay-bottle`, `overlay-cup` (`overlay-${vessel}`)
- `vessel-bottle`, `vessel-cup` (`aria-checked`)
- `hint`, `counter`, `user-chip`, `frame`, `switch-camera`
- `still` (a canvas, `canvas.dataset.testid='still'`)
- `upload`, `retry`, `discard`, `upload-home`, `banned`
- `beer-app` (`data-state="camera"`), `inapp-hint`, `back`

**Ids:** `#video` (class `is-mirrored`, `objectFit` "cover", `srcObject`), `#count`, `#success`, `#success-img`, `#success-total`, `#success-caption`, `#goal-short`, `#goal-long`.

**Classes:** `.beer-guide--bottle .beer-guide-line`, `.beer-guide--cup .beer-guide-line`, `.vb-notice`, `.vb-scrim`, `.vb-scrim input`.

**Roles:** `alert` (toast) filtered by "In 2 s nochmal"; in the notice: button "Neu laden", link "Zur Startseite"; `get_by_text("Kamera startet")`.

**Hooks:**
- `page.route("**/api/x/beer/upload")` (429 with/without `Retry-After`, 403 `uploads_paused`, abort)
- `page.route("**/api/identify")`
- a cancelable `beforeunload` dispatch (`leaving_is_blocked`)
- `document.querySelector('[data-testid=user-chip]').click()`, then `.vb-scrim` must exist; later `.vb-scrim` is **removed from the DOM by the test** and the shortcuts must work again
- `document.getAnimations()`

**Storage:** localStorage `vb_beer_vessel` and `vb_beer_inapp_dismissed` (behaviour only).

**Behaviours:**
- Default and toggle:
  - default bottle: `data-vessel=bottle`; overlay-bottle visible, overlay-cup hidden; `vessel-bottle` `aria-checked=true`;
  - hint exactly "Halte deine Flasche genau in den Umriss"; counter contains "0" and "1.000.000"; chip visible;
  - the cup toggle flips them; hint contains "Becher".
- Shoot and again:
  - shoot → success title exactly "Bier #1 geloggt 🍺"; `success-count` contains "1"; counter "1";
  - stored 1080×1440 with meta `{"vessel":"cup","facing":"environment"}`;
  - `again` → success hidden, shutter enabled, `still` count 0; second beer #2.
- Preview box:
  - `frame` is 3:4; `#video` and `overlay` boxes equal the frame ±1 px; centred; width ≥ viewport−24; `objectFit cover`;
  - bottle line height > 0.8×frame, cup > 0.7×frame; both centred ±2 px.
- The vessel choice survives reloads.
- `switch-camera` → `#video` gets `is-mirrored`; meta `facing:"user"`.
- 429 with `Retry-After: 2`:
  - the `upload` panel contains "Langsam! Zu viele Fotos auf einmal. In 2 s nochmal." and an alert toast;
  - `retry` disabled showing an "s" countdown; shutter disabled; `still` count 1; nothing stored;
  - `retry` becomes enabled with text exactly "Nochmal" within 4 s; the retry sends the same blob size (Chromium); stored.
- 429 without a wait: the panel contains "Zu viele Fotos auf einmal. Warte kurz" and `retry` is enabled.
- 403 `uploads_paused`:
  - the panel shows the server message "Deine Uploads sind gerade pausiert. Sprich die Gastgeber an."; `retry` hidden; `upload-home` visible; leaving is not blocked;
  - `discard` → camera, still 0; again refused; `upload-home` → `/`.
- Abort:
  - "Keine Verbindung"; `discard` → `upload` hidden, still 0, shutter enabled;
  - leaving is blocked while an unsent beer exists and unblocked after discard.
- gUM NotAllowedError: `.vb-notice` contains "Kamera geht nicht" and "Kamera-Zugriff wurde verweigert" with a "Neu laden" button; shutter disabled.
- Banned before load:
  - `banned` contains "Gesperrt"; exactly one `.vb-notice`; shutter disabled; `#video.srcObject === null`;
  - link "Zur Startseite" → `/`.
- Banned while on the page: shoot → `banned` notice; retry hidden; still 0; leaving not blocked; link home.
- Boot failure (identify aborted):
  - `.vb-notice` matches `Keine (Antwort|Verbindung)`; has link "Zur Startseite"; "Kamera startet" hidden;
  - "Neu laden" after unroute → shutter enabled and the notice is gone.
- Shortcuts while a dialog is open:
  - Space/Enter and typing "a b " in the dialog's input don't upload; `beer-app` `data-state=camera`;
  - after removing `.vb-scrim` and blurring, Space uploads.
- In-app UA (`+ " Instagram 300.0.0.0"`): `inapp-hint` contains "Safari oder Chrome"; its button dismisses it for good (survives a reload).
- Counter vs seq:
  - with 3 beers, 1 hidden: `#count` "2"; shoot → title "Bier #3 geloggt 🍺", `#success-total` "3", `#success-caption` contains "Bier #3", DB seq 4; `again` → `#count` "3".
  - running total 3 → shoot → #4: `success-togo` exactly "Noch 999.996 bis zur Million – weiter so!"; counter "4"; after +1000 DB rows, `again` → counter "1.004".
- Phone top bar: chip width ≥ 150; counter and back on screen; `#goal-short` visible, `#goal-long` hidden; counter "1 Mio.".
- Landscape 844×390:
  - frame height > 330 and 3:4; shutter, vessel-bottle, vessel-cup, switch-camera, back, counter, user-chip and hint all on screen; `#goal-long` visible;
  - success: again, home, success-title and success-count on screen; `#success` has no scrolling; `#success-img` height > 200.
- Portrait success: again, home and success-title on screen.

### 3g. test_booth_e2e.py

**Test ids:**
- `booth` with data attributes: `data-ready="1"`, `data-renderer` ∈ {`webgl`, `canvas2d`}, `data-filter`, `data-facing` ∈ {`user`, `environment`}, `data-mirror` ∈ {`1`, `0`}, `data-screen="camera"`
- `filter-strip` (class `is-fit` on desktop; children `[data-filter]` in catalogue order); `filter-{id}` (`aria-selected`); `filter-name`
- `preview`, `preview-canvas` (a WebGL canvas: `getContext('webgl')` plus `WEBGL_lose_context`)
- `shutter`, `result`, `result-photo` (`src` matches `^blob:`)
- `upload-status` (`data-state` ∈ {`done`, `error`, `uploading`}), `upload-retry`, `upload-home`
- `save`, `again`, `countdown-toggle` (`aria-pressed`), `countdown`
- `switch-camera`, `back` (`href="/"`), `user-chip`, `outbox`
- `leave`, `leave-stay`, `leave-go`, `banned`, `join`, `tile-booth`

**Other selectors:** `#video` (`srcObject`); `.vb-notice`, `.vb-scrim`, `.vb-scrim input`, `.vb-confetti`, `.vb-flash`, `.vb-toast-host`; class `vb-hidden` is added by a test.

**Roles:** `alert` (camera error with button "Nochmal versuchen"; "Ups" boot/catalogue notices with button "Neu laden" and link "Zur Startseite"); `status` or `alert` with the paused message; texts "Kamera startet", "Foto #1 ist hochgeladen ✓", "von vorhin ist jetzt hochgeladen".

**Hooks:**
- query param `?renderer=canvas2d`
- **IndexedDB `vb-booth` version 1, store `outbox`, keyPath `id`** (read directly by the test)
- `NO_INDEXEDDB`: `window.indexedDB` undefined
- CDP `Input.dispatchTouchEvent` (Chromium)
- `page.route("**/api/x/booth/upload")` (abort `internetdisconnected`, 429, 403, never answer); `**/x/booth/filters.json` abort; `**/api/identify` abort
- `beforeunload` check; `.vb-scrim` removal
- a layout constant: desktop chip width assumed 78 px (`middle = (lefts[0]+lefts[-1]+78)/2`)

**Storage:** localStorage `vb_booth_countdown` (behaviour).

**Behaviours:**
- Initial state: `data-renderer=webgl`, filter normal, facing user, mirror 1; chip ids equal FILTERS order; chip visible; back href `/`.
- A new guest from the QR sees consent before the camera (`data-ready` absent, `srcObject` null), then the booth is ready.
- Every filter selects without JS errors.
- Tap and swipe:
  - tap `filter-bw` → `filter-name` "Schwarz-Weiß", `aria-selected`;
  - a mouse swipe −160 → next filter, +160 → back; a touch swipe (CDP) also works; a 20 px swipe does nothing;
  - +160 on `normal` wraps to the last filter.
- Keyboard: ArrowRight → next filter, also while a chip has focus; Space (after blur) shoots; the stored filter matches.
- The selected chip is centred in the strip (<4 px) after 700 ms (portrait and landscape); the preview is 3:4 and wider than 0.7×min(viewport).
- bw capture:
  - `upload-status` "Hochgeladen ✓"; `save` visible; `result-photo` src `blob:`;
  - meta `{"filter":"bw","facing":"user"}`, 1080×1440, grayscale (`gray_error < 4`), stddev > 8.
- The party frame differs at the border (>40); the bottom band is warm and bright (r>200, r>b+60). The same holds after a WebGL context loss and in canvas2d.
- The frozen preview-canvas screenshot equals the stored photo (diff <8; mirrored diff > 2×). Not run on WebKit.
- A long party name ("Ömers & Jürgens legendäre Sommer-Gartenparty mit Überraschungsgästen 🎉🪩") appears in the title; party and retro capture OK.
- Countdown:
  - toggle `aria-pressed` false → true, remembered after reload;
  - countdown text "3" then "1"; result appears after 2.7–6 s.
- Save downloads `fotobox-1.jpg` (1080×1440); the button shows "Gespeichert ✓", then "Speichern" for the next shot.
- `switch-camera` → environment, mirror 0; the filter is kept after `again`; meta facing environment.
- A double click on `preview` flips the camera; the filter stays normal.
- Camera denied: alert "Die Kamera geht nicht" plus "Kamera-Zugriff wurde verweigert" with a "Nochmal versuchen" button; shutter disabled.
- 429 retry: status `error` "Langsam! Zu viele Fotos auf einmal. In 2 s nochmal."; `upload-retry` disabled showing "Nochmal in", then enabled with text exactly "↻ Nochmal hochladen"; retry → done.
- Offline:
  - "Keine Verbindung"; `again` → `outbox` "1 nicht hochgeladen"; clicking it (online) → hidden, plus "Foto #1 ist hochgeladen ✓".
  - The unsent photo survives a reload (IndexedDB count 1, leaving not blocked); the next online visit sends it: "von vorhin ist jetzt hochgeladen", outbox hidden, IndexedDB 0.
- Back with 2 unsent:
  - `leave` sheet "2 Fotos sind noch nicht hochgeladen" and "sobald du die Fotobox wieder öffnest"; the URL is unchanged;
  - shortcuts are inert while it is open;
  - `leave-stay` closes and retries; Escape closes; `leave-go` → `/` with `tile-booth` visible;
  - back online, both are sent; Back with nothing unsent goes straight home.
- Without IndexedDB: leaving is blocked after a failed shot; `leave` shows "Wenn du jetzt gehst, ist es weg."; `leave-stay` retries; "Foto #1 ist hochgeladen ✓".
- Mid-upload: status `uploading` and leaving is blocked.
- Boot failure: alert "Ups" matching `Keine (Antwort|Verbindung)`, link "Zur Startseite", "Kamera startet" hidden; "Neu laden" → ready, no `.vb-notice`.
- `filters.json` failure: "Ups" alert with "Neu laden".
- Shortcuts wait while the Instagram dialog is open (arrows, Space, Enter, typing, ArrowLeft in the field); after removing `.vb-scrim` they work.
- Banned on load: `banned` "Gesperrt", one `.vb-notice`, no camera; link home.
- Banned mid-party:
  - status `error` containing "gesperrt"; `upload-retry` and `again` hidden; `upload-home` and `save` visible; not blocked;
  - Escape → the `banned` notice; outbox hidden; link home.
- Paused:
  - status shows the paused message; no retry; home and save visible; not blocked;
  - `again` → outbox hidden, no `banned`; back → `/`.
- Paused while a kept photo exists: after a reload a status/alert shows the message, outbox hidden, IndexedDB 1, not blocked; after the pause ends, "von vorhin ist jetzt hochgeladen".
- Landscape 844×390:
  - shutter, countdown-toggle, back, user-chip and preview on screen;
  - result: save, again, upload-status and result-photo on screen; `result` not scrolling; photo height > 250.
- Portrait: chip ≥150 px, back on screen; after an offline shot, outbox, chip and back on screen with chip ≥100 px.
- Desktop:
  - `filter-strip` has `is-fit`; all chips inside it and centred as one group; strip doesn't scroll;
  - ArrowLeft wraps without moving `filter-normal`;
  - resizing to 390 removes `is-fit`.

### 3h. test_desktop_e2e.py

`DESKTOP` context with the WEBCAM test card.

**Selectors:**
- `tid:` `tile-beer`, `tile-booth`, `shutter`, `switch-camera` (must be hidden), `frame`, `vessel-bottle`, `vessel-cup`, `back`, `counter`, `overlay` (the test sets `style.display='none'`), `success`, `again`, `success-title`, `booth`, `preview`, `preview-canvas`, `countdown-toggle`, `filter-normal`, `upload-status`, `result`, `save`, `conn`, `join`, `filter-party`
- `#video.is-mirrored`, `#password`, `#panel-sperren`
- `[data-testid=photo-card|photo-tile|guest-row|audit]`

**Hooks:** `window.__cameraRequests`; `UPLOAD_JS` raw fetch.

**Behaviours:**
- Home tiles are one centred column (width ≤ 560); Enter on the focused tile → `/x/booth/`.
- Beer on desktop:
  - a single gUM request with `facingMode == {"ideal": "environment"}`; switch hidden; the video is mirrored;
  - frame is 3:4, height > 0.6×800, centred; controls on screen and within 300 px of the centre; no horizontal scroll;
  - the frame screenshot (overlay hidden) is the centre portrait crop, mirrored;
  - keyboard: Space shoots → `again` focused; Enter → success hidden and shutter focused; Space → "Bier #2 geloggt 🍺"; Escape closes;
  - stored meta `{"vessel":"bottle","facing":"user"}` ×2, 1080×1440, correct crop.
- Booth on desktop:
  - webgl, user, mirror 1, switch hidden; preview 3:4, > 0.6×800, centred; controls on screen; the preview-canvas crop is correct;
  - dblclick doesn't re-request the camera (1 request);
  - ArrowRight/Left; Space shoots; Escape → result hidden and shutter focused; arrows work while the shutter is focused; Enter on the shutter shoots; save/again on screen;
  - stored meta normal/user ×2 with a correct crop.
- Admin on desktop:
  - keyboard login (`#password` + Enter);
  - each screen shows its element with `conn` live and no horizontal scroll;
  - manage shows 3 tiles in one row (same y).
- `test_screenshots` (optional, desktop and phone) asserts only navigation steps plus `.vb-notice` "Kamera-Zugriff wurde verweigert".

### 3i. test_firefox_e2e.py (Firefox only)

**Selectors:** `tid:join`, `tid:shutter`, `get_by_text("Kamera startet")`, `get_by_role("alert")`, `.vb-notice` with its button.

**Hooks:** `window.__cameraRequests` (SPY), `navigator.permissions.query({name:'camera'})`.

**Behaviours:**
- No gUM before consent (`__cameraRequests.length == 0`).
- ASK:
  - "Kamera startet" stays visible; exactly one request with `audio === false` and `video.facingMode.ideal` ∈ {user, environment};
  - permission state `prompt`; shutter disabled; no alert; no JS errors.
- ALLOW: shutter enabled; state `granted`.
- BLOCK:
  - `.vb-notice` contains "Kamera geht nicht" (beer) or "Die Kamera geht nicht" (booth);
  - plus "Kamera-Zugriff wurde verweigert. Klick in der Adressleiste auf das Kamera-Symbol" (desktop) or "... Tippe auf das Schloss" (touch);
  - a button; shutter disabled; state `denied`; exactly 1 request.

### 3j. Cross-cutting DOM and JS contract

1. **Core SDK module URLs and exports:**
   - `/static/core/vb.js`: `boot`, `openCamera`, `captureFrame`, `canvasToJpeg`, `uploadJpeg`, `mountUserChip`, `api`, `fatal`, `sheetOpen`; `ApiError` with `name`, `status`, `code`, `retryAfter`, `message`.
   - `/static/core/camera.js`: `cameraErrorMessage`.
   - `/static/core/device.js` must stay optional (blockable).
   - `/static/core/vb.css`; `/static/core/loader.js` (classic script giving the `load-failed` fallback).
2. **Server-rendered gate and 404 pages:** `tid:gate`, "Scan den QR-Code", "Hier ist nichts", `.vb-notice-emoji`.
3. **Dialogs:** "dialog open" means a `.vb-scrim` exists in the DOM. Tests remove it directly and expect the app to resume, which is risky with a virtual-DOM framework.
4. **Hooks the tests create themselves (no app globals):** `window.__cameraRequests` comes from test init scripts. The app has no `window.__vb`-style global; tests reach the SDK only through `import()`.
5. **Fake camera expectations:** the app calls `MediaDevices.prototype.getUserMedia` with `{audio:false, video:{facingMode:{ideal:...}, width:{ideal:1920}, ...}}`, retries `{audio:false, video:{facingMode:'environment'}}` on OverconstrainedError, and uses `enumerateDevices` and `getSettings().facingMode` to decide `canSwitch` and mirroring.

---

## 4. API contract checked by unit/API tests, and internal coupling

### 4a. Endpoints, status codes, error codes and fields

**Entry and gate**
- `GET <path>?t=TOKEN` → 303, `Location` without `t` (other params kept; `//evil.example/` becomes `/evil.example/`).
- `Set-Cookie: vb_access` (HttpOnly; SameSite=Lax; Secure on https or with an https `public_base_url`); HSTS `max-age=31536000` on https only.
- Bad or missing token → 404 gate HTML. JSON routes → 404 `{"error":"scan_qr"}`.

**`POST /api/identify`** (`{}` | `{"fp"}` | `{"uid"}`)
- `state` ∈ {`needs_consent`, `ok`, `banned`}; `consent.version` "1"; `consent.paragraphs`.
- `uid_token` (format `public_id.signature`); `user` keys exactly {`name`, `instagram`, `banned`, `uploads_paused`}; `uploads_stopped`.
- Sets the `vb_uid` cookie when the uid token restores identity; `Cache-Control: no-store`.

**`POST /api/join`** (`{"accept": true, "version": "1", "instagram", "fp": {"hash", "components"}}`)
- 201 new / 200 known; `state`, `user`, `uid_token`, `already_joined`, `instagram_kept`.
- Errors: 422 (`accept` false or no `fp`), 409 `consent_outdated`, 400 `invalid_instagram`, 429 plus `retry-after`.
- A banned fingerprint gives `state banned`.

**`PATCH /api/me {"instagram"}`** → `{"user":{...}}`; 400 on a bad handle; 403 `bad_origin` (Origin missing or foreign); a same-origin `Referer` is accepted.

**`GET /api/extensions`** → `{party_name, extensions:[{id, title, emoji, tagline, url:"/x/{id}/", uploads}]}`.

**`POST /api/x/{ext}/upload`** (JPEG body, header `X-VB-Meta` = URL-encoded JSON)
- 201 `{photo:{id, seq, width, height,...}}` plus extension extras (`count`; `beer_number`/`total`; `booth_number`).
- Error codes:
  - 404 `scan_qr`; 404 unknown extension;
  - 401 `needs_consent`;
  - 403 `banned`, `uploads_paused` (exact message), `uploads_stopped` (exact message);
  - 400 `invalid_image`, `invalid_meta` (with `message`);
  - 415 wrong content type; 413 too large; 429 with `Retry-After`.

**`GET /api/x/beer/stats`** → `{"total", "goal": 1000000}`.

**`GET /media/{id}`** (`?thumb=1`, `?download=1` gives `Content-Disposition: attachment`): visible to owner and admin only; 404 otherwise.

**`HEAD /healthz`** → 200.

**Headers:** CSP `default-src 'self'`…, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` contains `camera=(self)`. JSON bodies over the cap → 413; chunked → 411.

**Admin session**
- `POST /api/admin/login`: 200 sets `vb_admin` (HttpOnly; SameSite=Strict); 401 `wrong_password`; 429 lockout; 403 without Origin.
- `GET /api/admin/session` → `{"authenticated"}`; `POST /api/admin/logout`.

**Admin pages:** `GET /admin` → `/admin/live`; `/admin/{live,manage,user}` → 303 `/admin/login?next=...` (query encoded `%3F`/`%3D`); `/admin/login` public; `/admin/assets/*` public.

**Admin API** (all routes: 401 `admin_required`; mutations: 403 `bad_origin`)
- **Photos**
  - `GET /photos` → `{photos[], total (first page only), next}`; params `limit` 1..200, `before`/`after` cursors (`invalid_cursor`), `hidden`, `user_id`, `extension` (400 on bad values).
  - Photo object: `id`, `extension`, `seq`, `thumb_url`, `hidden`, `hidden_reason`, `user{name, instagram, uploads_paused,...}`.
  - `GET /photos/{id}` → `{photo}`.
  - `POST .../hide|unhide` → `{changed, photo}`.
  - `DELETE` → `{"ok": true, "id"}`.
  - `POST /photos/bulk {ids (1..200), action}` → `{action, changed, unchanged, missing}`.
- **Users**
  - `GET /users` (`search`, `banned`, `paused`, `limit`, `offset`) → `{users[], next_offset}`; user fields `id`, `instagram`, `photo_count`, `banned`, `auto_banned`, `auto_ban{fp_hash, source_user_id, source_user_name}|null`, `uploads_paused_source`.
  - `GET /users/{id}` → `{user{instagram, fp_components, consent_at, banned, ban_reason, auto_banned}, photos, fingerprints[{fp_hash, current, banned, shared_with, users[{id, name, instagram, banned, auto_banned}]}], sharing}`.
  - `POST /users/{id}/ban {reason ≤200, fingerprint}` → `{changed, fingerprint_banned, user, photos}`; 400 `no_fingerprint`.
  - `POST /users/{id}/unban {fingerprint?}` → `{changed, user, fingerprints_unbanned, users_unbanned}`.
  - `POST /users/{id}/uploads {paused}` → `{changed, user{uploads_paused, uploads_paused_source, uploads_lock_period, uploads_paused_at}}`.
- **Device bans:** `GET /device-bans` → `{bans[{fp_hash, reason, source_user_id, source_user_name, users[{id, auto_banned}]}]}`; `DELETE /device-bans/{hex64}` → `{users_unbanned,...}`.
- **Overview**
  - `GET /stats` → `{photos, visible, hidden, deleted, guests, banned, instagram, instagram_handles, uploaders, fingerprint_bans, extensions{id:{photos, hidden}}, last_upload_at}`.
  - `GET /instagram` → `{handles[{handle, photos, visible, hidden, users, last_upload_at, recent}]}`.
  - `GET /audit?limit&before` → `{entries[{id, action, target, actor, details}], next}`.
  - `GET /extensions` → `{extensions[{id, emoji, loaded, meta_labels}]}`.
- **Events:** `GET /events` is SSE (`text/event-stream`, `retry:`, `event:`, `data:`); the stream ends after logout (session recheck).
- **Upload switches**
  - `GET/POST /upload-stop {enabled}` → `{enabled, since, by, changed}`.
  - `GET/POST /upload-pause {enabled, restore}` → `{enabled, since, period, by, affected, paused_total, changed, restored, kept}`; 400 `restore_required`.

**Audit actions:** `admin.login`, `admin.login_failed`, `photo.hide/unhide/delete`, `user.ban/unban`, `fingerprint.ban/unban`, `user.uploads_pause/unpause`, `uploads.lock_on/lock_off`, `uploads.stop/resume`.

**Event types:** `photo.created`, `user.created`, `photo.hidden/unhidden/deleted`, `user.banned/unbanned`, `fingerprint.banned/unbanned`, `user.uploads_changed`, `settings.upload_pause`, `settings.upload_stop`.

### 4b. Tests reaching into backend internals (break if the backend is restructured)

- **Imports:**
  - `virtubooth.app.create_app`; `virtubooth.config.{Settings, ConfigError}` (+ `Settings.from_env`); `virtubooth.context.{Core, Limits}`
  - `virtubooth.extension.{Extension, UploadPolicy, discover_extensions}`
  - `virtubooth.repo.{PhotoQuery, Repo, Photo, User, PAUSE_ADMIN, PAUSE_NEW_GUEST_LOCK}`
  - `virtubooth.db` as a module, using `MIGRATIONS` (monkeypatched), `SCHEMA`, `SCHEMA_VERSION`, `Database`
  - `virtubooth.events.{EventBus, format_sse}`; `virtubooth.names.pseudonym`; `virtubooth.identity.normalize_instagram`; `virtubooth.errors.ApiError`; `virtubooth.security.origin_allowed`; `virtubooth.logs.AccessLogFilter`
  - `virtubooth.admin.queries.AUTO_BAN_REASON`; `virtubooth.admin.api.router` (with FastAPI router internals `original_router`, `include_context.prefix`); `virtubooth.admin.api.SESSION_RECHECK_SECONDS` (monkeypatched in e2e)
  - `virtubooth.ratelimit.RateLimiter`; `virtubooth.pages.{STATIC_DIR, ADMIN_STATIC}`
  - `virtubooth.extensions.beer` (`.extension`); `virtubooth.extensions.booth` (`.extension`, `FILTERS`, `load_filters`)
  - `virtubooth.tools.{_common, export, qr, timelapse}`, including private `export._cell`, `_common.scratch_parent`, `timelapse.run_ffmpeg` (monkeypatched), `qr.discover_extensions` (monkeypatched)
- **Core internals:**
  - `core.repo.*` (≈40 methods across the suite)
  - `core.signer.unsign("uid", cookie)`
  - `core.db.all/one/close` (raw SQL)
  - `core.bus.bind_loop/subscribe/subscriber_count`
  - `core.limits.<name>` replaced with `type(x)(rate, per)` (names: `login_ip`, `login_ip_hourly`, `login_failures_global`, `api_ip`, `api_guest`, `new_user_ip`, `upload_user`, `upload_ip`)
  - `core.settings` swapped via `dataclasses.replace`; `core.extensions[...]` replaced
  - `app.state.core`
- **Raw schema knowledge:** the v1 column counts and order for 6 tables, and the `settings` table (`test_core_db_migration`).

---

## 5. Content-blocker naming test

**Files:** `tests/blockerlists.py` (matcher, no third-party code), `tests/test_core_blockers.py`, `tests/fixtures/blocker_rules.txt`. The vendored rules are grouped under `! list: <title>` blocks, selected on 2026-10-12/13 into four groups:
- **[A]** rules that once blocked the app (`/static/core/fingerprint.js`)
- **[B]** network rules whose key literal occurs in one of the app's URLs (near misses)
- **[C]** generic rewrite rules (`$removeparam`, `$permissions`, `$csp`, ...)
- **[D]** generic element-hiding rules naming similar classes/ids/test ids, or consent/cookie/notice/modal-like attributes

### What is scanned

**`app_requests(app, token)`** builds about 80+ (asserted `> 80`) `Request(url, type, method, source)` on `BASE = https://party.example.com`:
- **Static files:** every file (recursive, skipping `__pycache__`) of `pages.STATIC_DIR` → `/static/<rel>`; `ADMIN_STATIC/assets` → `/admin/assets/<rel>`; each loaded extension's `static_dir` → `/x/<id>/<rel>`. The type comes from the suffix (`.js`/`.mjs`=script, `.css`=stylesheet, `.html`=document, `.json`=xhr, `.svg`/`.png`/`.jpg`=image, `.woff2`=font, `.webmanifest`=other).
- **Documents:**
  - `ADMIN_STATIC/*.html` → `/admin/<stem>`;
  - `/`, `/healthz`, `/admin`, `/admin/login?next=%2Fadmin%2Flive`, `/admin/user?id=17`, `/admin/manage?tab={fotos,gaeste,instagram,sperren,protokoll}`, `/?t=<token>`;
  - per extension: `/x/<id>`, `/x/<id>/`, `/x/<id>/?t=<token>`, `/x/<id>/?debug=1`.
- **Media:** `/media/kQ3x_vN8aLp2Rt0Y` and `?thumb=1` (image and other), `?download=1` (document).
- **API:** every `/api/` route from `app.routes` (walking included routers), with `{ext_id}` → each extension, `{public_id}`/`{photo_id}` → the fixed photo id, `{user_id}` → 17, `{fp_hash}` → `"3f9a"*16`; every method except HEAD.
- **API extras:**
  - `/api/admin/events` as `other` (EventSource);
  - `/api/admin/photos?limit=60`, `?limit=60&before=<id>`, `?limit=200&after=<id>&extension=beer&hidden=all&user_id=17`;
  - `/api/admin/users?search=giraffe&banned=true&limit=100&offset=0`;
  - `/api/admin/audit?limit=100&before=5`.
- **URLs in JS:** every literal in JS files matching `['"`](/(?:api|media|admin|static|x)/[^'"`\s]*|\./[\w.-]+\.(?:js|json|css))['"`]` (`${...}` replaced by `x`; `./` resolved against the file's prefix).

**`ui_elements(app)`** builds element trees (asserted `> 500` elements) from every file under `STATIC_DIR`, `ADMIN_STATIC` and each extension's `static_dir`:
- `.html` → a parsed DOM tree.
- `.js` → three things:
  1. `h('tag', {attrs}, ...children)` calls as nested trees (a tolerant scanner, not a JS parser). It reads literal `class` (including fragments in template/ternary strings), other literal attributes (`id`, `data-testid`, `role`, `aria-*`, `for`, `name`, ...), skips `dataset`/`on*`, takes string children as text, and resolves identifier children to the nearest earlier `const x = h(...)`.
  2. `loader_tree`: classic `var x = document.createElement('tag')` / `.className =` / `.setAttribute('k','v')` / `.textContent =` / `.appendChild` (this is how `loader.js`'s `load-failed` box is seen).
  3. `loose_names`: names from `classList.add|toggle|remove|contains('...')` and `className = '...'`.
- `.css` → `loose_names`: every `.class` and `#id` token in selectors (comments and `url()` stripped; hex colours skipped), each as a standalone `div`.
- Each element's `origin` is its path, e.g. `virtubooth/static/core/vb.js`, `admin/static/assets/admin.js`, `beer/static/beer.js`.

### How matching works

**`NetworkRules`** (EasyList/uBO/AdGuard syntax subset):
- **Line handling:** comments `!`/`[` and cosmetic lines are skipped; hosts-file lines (`0.0.0.0 host`) become `||host^`.
- **Prefilter:** a rule is dropped unless its `||host`, or its longest literal (≥3 chars), occurs in the corpus of request URLs.
- **Options:**
  - types plus aliases (`xhr`, `css`, `doc`, `frame`, `beacon`, `1p`, `3p`);
  - `third-party` is dropped unless negated (our requests are first-party); `first-party`/`strict1p`;
  - `domain|from|to|denyallow`; `method`;
  - `removeparam`/`queryprune` and modifiers (`csp`, `permissions`, `replace`, `urltransform`, `uritransform`, `urlskip`, `removeheader`, `responseheader`, `jsonprune`, `xmlprune`, `hls`) count as hits when they apply;
  - non-blocking options are dropped; `badfilter` removes the matching rule; `match-case`, `important`;
  - unknown options are skipped as un-evaluable.
- **Default types:** everything except document/popup/popunder; `||host^` and modifier rules also cover document; `csp`/`permissions` cover document/subdocument only.
- **Patterns to regex:** `||` → scheme + optional subdomains; `|` → anchor; `^` → `(?:[^\w.%-]|$)`; `*` → `.*`; `/regex/`.
- **`check(req)`:**
  - non-exception rules that apply (type, first-party, method, domain/to, regex);
  - cancelled by `@@` exceptions of the same action unless `$important`;
  - `removeparam` counts only if a query parameter actually matches (exact name, `/regex/`, or `~` negation);
  - `permissions` counts only if its value mentions `camera`.

**`CosmeticRules`:**
- Only **generic** element-hiding rules: domain part empty, `*`, or only `~negated`. Separators `##`, `#?#`, `#$#` (CSS-injection selector before `{`), `#@#` (exceptions honoured).
- `:style()`, `:remove()`, `:remove-attr()`, `:remove-class()` suffixes are stripped; scriptlets `+js(` and HTML filters `^` are skipped.
- Selector engine:
  - supported: compound tag/`.class`/`#id`/`[attr op value i]` (ops `=`, `~=`, `|=`, `^=`, `$=`, `*=`); combinators descendant, `>`, `+`, `~`; `:not`, `:is`, `:matches`, `:where`, `:has`, `:-abp-has`, `:has-text`, `:contains`, `:-abp-contains`, `:nth-*`, `:first/last/only-child/of-type`, `:empty`, `:root`, `:link`/`:any-link`;
  - pseudo-elements and other procedural pseudos raise `SelectorError` and are not evaluated;
  - indexed candidate lookup by id, class, attribute or tag.

### The 7 tests

1. **`test_vendored_rules_still_catch_what_broke_the_app`** (sanity, frontend-independent):
   - `/static/core/fingerprint.js` is hit by "EasyPrivacy: `/fingerprint.js^$domain=~github.com`" and "AdGuard Tracking Protection: `/fingerprint.js^`";
   - a synthetic `div[data-testid="consent-banner"]` is hidden by `[data-testid="consent-banner"]`;
   - `main#app > div.cookie` is hidden by `#app > .cookie`.
2. **`test_app_urls_survive_vendored_rules`:** `network_hits(requests, vendored) == []`.
3. **`test_ui_survives_vendored_cosmetic_rules`:** `cosmetic_hits(elements, vendored) == []`.
4. **`test_join_dialog_avoids_cookie_notice_words`:**
   - exactly one element with `data-testid="join"` whose `origin` ends with `core/vb.js`;
   - its subtree contains `role="dialog"`;
   - no `class`, `id`, `data-testid`, `aria-labelledby`, `for` or `name` value in the subtree contains (case-insensitive substring) any of `COOKIE_NOTICE_WORDS = ("consent", "cookie", "gdpr", "banner", "notice", "modal", "backdrop", "privacy", "popup")`.
5. **`test_url_paths_avoid_blocker_words`:** no request's **URL path** (lower-cased; the query is not checked) contains any of `TRACKING_WORDS = ("fingerprint", "track", "analytic", "telemetry", "beacon", "pixel", "advert", "/ads", "/ad/", "collect")` + `COOKIE_NOTICE_WORDS`.
6. **`test_app_urls_survive_full_lists`** (opt-in with `VB_BLOCKLISTS=<dir>`): same as test 2 against 28 downloaded lists (EasyList, EasyPrivacy, EasyList Germany, uBO filters/privacy/badware/unbreak/quick-fixes/annoyances/annoyances-cookies/URL-tracking, AdGuard base/tracking/social/german/mobile/url-tracking/cookies/popups/other-annoyances, Fanboy annoyance/social/cookiemonster/mobile-notifications, Brave first-party/cookie-specific, Peter Lowe hosts, HaGeZi Pro). Lists are downloaded when missing; skipped if none can be fetched.
7. **`test_ui_survives_full_lists`** (opt-in): same as test 3 against the full lists.

**Related e2e test** `tests/e2e/test_core_e2e.py::test_static_file_names_avoid_blocker_keywords` (marked e2e but purely filesystem):
- Scans file **names** with suffix `.js`, `.css`, `.html`, `.json`, `.svg` under `STATIC_DIR`, `STATIC_DIR.parent/"admin"/"static"`, `STATIC_DIR.parent/"extensions"`.
- Regex (case-insensitive): `fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]`.

### Key vendored rules (quoted)

- **Network:**
  - `/fingerprint.js^` (AdGuard Tracking Protection); `/fingerprint.js^$domain=~github.com` (EasyPrivacy)
  - `/W*ity0*00Er00*/index.$document`
- **Query parameters that would be stripped:**
  - `$removeparam=_gl`, `awc`, `gci`, `maf`
  - `$removeparam=/^__s=[A-Za-z0-9]{6\,}/`, `/^at_custom/`, `/^cm_mmc/`, `/referrer=appmetrica_tracking_id/`
  - `$removeparam=elq`, `removeparam=a8`, `removeparam=_ga`
- **`*$permissions=...=()`** for attribution-reporting, browsing-topics, compute-pressure, idle-detection, join-ad-interest-group, keyboard-map, private-aggregation, private-state-token-*, run-ad-auction. These are ignored because none touch `camera`.
- **Cosmetic, cookie-notice style:**
  - `##[data-testid="consent-banner"]`, `##[data-testid="cookie-bar"]`, `##[data-testid="accept-cookies-banner"]`, `##[data-testid="cookieConsentBanner"]`, `##[data-testid="cookienotice-container"]`, `##[data-testid="cookies-module"]`, `##div[data-testid="cookiePopup"]`, `##div[data-testid="cookies-dialog"]`
  - `###app > .cookie`, `###app > .cookies`, `###app > #cookies`, `##.cookies-allowed[role="dialog"]`, `##.CookieBanner:not(body):not(html)`, `##.cookieWarning`, `##.GDPR-cookies`, `##.consent-cookies-dialog`, `###privacy-consent-banner`
  - `##div[class^="app_gdpr"]`, `##[class^="cookieBox-"]`, `##.q-notification[class*="gdpr"]`, `##.reveal-modal[id*="cookie"]`, `##.react-reveal[class*="cookie-banner"]`, `##.s--message[class*="cookie-notice"]`
  - uBO: `*###cookie-msg`, `*###cookieBox`, `*###cookie_notice`, `*###gdpr-cookie-message`, `*##.cookie_content`
- **Cosmetic, ad/banner/overlay style:**
  - `##[data-testid="adBanner-wrapper"]`, `##[id^="section-ad-banner"]`, `###ad-overlay`, `###AdPopUp`, `###popupAd`, `##.adOverlay`, `##.bannerAd`, `##.ad-banner-container`, `##.hor_banner`, `##.werbebanner`
  - `##.appBanner:not(body)`, `##.smartbanner--ios`, `##amp-app-banner`, `##.branch-banner`, `###push-overlay`, `##.modal-push`, `##.gt-popup`, `##.sqs-popup-overlay`, `##.seva-overlay`
  - `##body #notificationPopup`, `##.blocker-notice`, `##.blocker-overlay` (relevant because the app shows a "Blocker" hint), `###uglipop_overlay`, `###newsletterOverlay`, `##.sharing-popup`, `##.close-wrap > .close-overlay`, `##.grid > .container > #aside-promotion`

### Invariants a new frontend build must satisfy

1. **URL paths** (served files, including directory names and hashed chunk names, and API routes) contain none of: `fingerprint track analytic telemetry beacon pixel advert /ads /ad/ collect consent cookie gdpr banner notice modal backdrop privacy popup`. Component-named chunks like `Modal-xxxx.js`, `Notice.js`, `collection.js`, `PrivacyNote.js`, and an API route like `/api/consent` would fail. The join route must stay neutral (`/api/join`).
2. **Served file names** don't match `fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]` (case-insensitive). The `ads?[-_./]` part also catches `upload.js`, `download-…`, `Thread.js`, `Load.js` and **random content-hash fragments** such as `index-Ad_3f.js` or `…ads-….js`. Bundler hash names can therefore fail this test flakily unless their naming or alphabet is controlled.
3. **No URL is hit by** `/fingerprint.js^`, the `$removeparam` parameter names above, or any camera-touching `$permissions`. With `VB_BLOCKLISTS`, none of the full lists may block or rewrite any of them either.
4. **No element** (from HTML, built DOM, CSS class/id tokens or classList names) matches a generic cosmetic rule. Watch especially for:
   - an `#app` root with a `.cookie`/`.cookies`/`#cookies` child;
   - any `*cookie*`/`*gdpr*`/`*consent-banner*` test ids or classes;
   - `.blocker-notice`/`.blocker-overlay`, `#push-overlay`, `.modal-push`, `.gt-popup`, `.appBanner`, `.smartbanner--ios`, `*-overlay` names from the lists.
5. **The join dialog** has `data-testid="join"` and contains `role="dialog"`. None of its `class`/`id`/`data-testid`/`aria-labelledby`/`for`/`name` values contain `consent cookie gdpr banner notice modal backdrop privacy popup`. Today it is `.vb-sheet` in `.vb-scrim`, with ids `vb-join-title`/`vb-join-insta`. A framework "Modal"/"Backdrop" component class name would fail.
6. **Runtime counterpart** (e2e): optional modules (device fingerprinting, today `device.js`) are loaded by dynamic `import()` in try/catch; consent still works with a fallback fingerprint (`fp_components.fallback=True`); a blocked main module shows the `load-failed` hint containing "Blocker" through a classic `loader.js`.

**Effect of a TS rewrite on the scanner:** `ui_elements` understands only HTML files, `h('tag', {...})` calls, classic `createElement` code, CSS selector tokens and `classList`/`className` literals.
- With JSX/TSX or compiled bundles, the h()-scanner finds almost nothing. `elements > 500` may fail, and the cosmetic checks become vacuous.
- `test_join_dialog_avoids_cookie_notice_words` hard-codes `origin.endswith("core/vb.js")`.
- `ui_elements` needs a new source of DOM: for example, render each page in Playwright and serialise the live DOM (needs a browser), or walk the JSX AST plus the built CSS.
- The network/path tests should keep working if the built files are served from the same directories, since `app_requests` walks the disk and scans JS string literals.

---

## 6. Summary

### Counts
- **Unit/API (default run):** 211 functions, 306 collected cases.
  - Skips: 2 cases without `VB_BLOCKLISTS`; 6 without ffmpeg; 1 when run as root.
- **E2E (`-m e2e`):** 123 functions, 140 cases.
  - Skipped by environment or browser: booth `test_screenshots` (needs `VB_BOOTH_SCREENSHOTS`); desktop `test_screenshots` ×2 (needs `VB_SCREENSHOT_DIR`); firefox ×8 unless Firefox; 3 `needs_clipboard` on WebKit; booth `test_photo_is_exactly_the_preview` on WebKit.
- Default CI (`pytest -m e2e`) covers **Chromium only**. Firefox needs the env variable; WebKit needs Docker.

### A. Survive a frontend rewrite unchanged (no frontend dependency): 188 unit functions plus 3 e2e
- `test_admin_api.py` (all 31)
- `test_admin_upload_controls.py` (all 17)
- `test_core_admin_auth.py` (all 12)
- `test_core_access.py` (all 38). Caveat: `test_pages_without_token_show_scan_qr`, `test_wrong_token_shows_gate_and_sets_no_cookie` and `test_unknown_page_with_access_is_plain_not_found` need the server-rendered gate/404 pages to keep "Scan den QR-Code" / "Hier ist nichts".
- `test_core_db_migration.py` (4), `test_core_uploads.py` (16), `test_tools.py` (44)
- `test_beer.py` API tests (14): `test_extension_definition` (still needs `static_dir/index.html`), `test_upload_returns_beer_number_and_total`, `test_stored_photo_is_1080x1440`, `test_invalid_meta_rejected`, `test_unknown_meta_key_rejected`, `test_facing_null_is_dropped`, `test_image_size_limits`, `test_upload_needs_consent`, `test_banned_guest_cannot_upload`, `test_stats_requires_access`, `test_stats_counts_visible_beers`, `test_rejects_wrong_frame_size`, `test_stats_ignores_other_extensions`, `test_listed_on_home`
- `test_booth.py` API tests (9): `test_extension_is_listed`, `test_upload_stores_meta_and_numbers_photos`, `test_every_catalogue_filter_is_accepted`, `test_invalid_meta_is_rejected`, `test_missing_or_extra_meta_is_rejected`, `test_oversized_image_is_rejected`, `test_upload_needs_consent`, `test_load_filters_rejects_bad_catalogues`, `test_filter_catalogue` (keep `static/filters.json` where the backend loads it)
- `test_admin_pages.py`: `test_pages_need_admin`, `test_login_page_is_public` (keep `id="password"`)
- `test_core_blockers.py`: `test_vendored_rules_still_catch_what_broke_the_app`
- e2e: `test_admin_e2e::test_event_stream` (HTTP-only SSE), `test_core_e2e::test_gate_without_token` (server gate page), `test_core_e2e::test_static_file_names_avoid_blocker_keywords` (filesystem; survives if built assets stay under the same roots and the naming invariant above holds)

### B. Static-source unit tests that must be retargeted to the new source or build layout (23 functions)
- **`test_admin_pages.py` (8):** `test_expected_files_exist`, `test_pages_served_to_admin` (`src="/admin/assets/{page}.js"`), `test_assets_are_public_with_right_types` (admin.js/admin.css names), `test_html_is_csp_safe` (keep the intent for built HTML), `test_html_references_resolve`, `test_js_avoids_unsafe_dom_and_csp_traps` (framework runtimes contain `innerHTML` etc.; run it on sources), `test_js_imports_resolve`, `test_live_screen_cannot_delete`.
- **`test_beer.py` (4):** `test_page_requires_access`, `test_page_assets_served`, `test_page_is_csp_clean` (test-id set), `test_every_element_the_page_script_looks_up_exists`.
- **`test_booth.py` (5):** `test_every_catalogue_filter_has_an_implementation` (filters.js regex), `test_page_is_served_to_party_guests` (exact script tag and file list), `test_static_files_follow_the_csp_rules`, `test_every_element_the_page_script_looks_up_exists`, `test_outbox_store_is_best_effort`.
- **`test_core_blockers.py` (6):**
  - `test_app_urls_survive_vendored_rules`, `test_url_paths_avoid_blocker_words` and `test_app_urls_survive_full_lists` probably keep working if built files are served from the scanned directories (the `> 80` request count must still hold);
  - `test_ui_survives_vendored_cosmetic_rules`, `test_ui_survives_full_lists` and `test_join_dialog_avoids_cookie_notice_words` need a new DOM extractor.

### C. E2E tests that need only selector updates: 101 functions
They survive unchanged if the new frontend keeps the DOM contract in section 3 (test ids, ids, roles/names, German texts, `data-*` state attributes, a few classes such as `is-hidden`, `is-mirrored`, `is-fit`, `vb-sheet--more`, `.vb-notice`, `.vb-toast`, `.adm-badge--*`). Otherwise only selectors change. All of them also need runtime CSP cleanliness (`js_errors == []`) and the same served URLs.
- `test_core_e2e`: `test_consent_then_home`, `test_edit_instagram_from_chip`
- `test_core_ui_e2e` (14): `test_join_button_is_on_screen_on_small_phones`, `test_join_dialog_scroll_hint_goes_away_at_the_end`, `test_party_name_shows_before_joining`, `test_join_errors_say_what_is_wrong_with_the_handle`, `test_pasted_profile_link_keeps_just_the_handle`, `test_second_tab_joining_keeps_its_handle`, `test_second_tab_with_another_handle_is_told_which_one_counts`, `test_user_chip_shows_the_handle_and_ellipsizes`, `test_home_offers_a_reload_when_identify_is_blocked`, `test_home_says_offline_when_the_phone_is`, `test_home_failure_shows_the_api_message_and_retry_after`, `test_debug_log_lets_taps_through_and_folds`, `test_danger_button_text_is_readable` (uses core CSS classes `vb-btn vb-btn--danger`), `test_gate_and_404_emoji_are_big`
- `test_admin_e2e`: all except `test_event_stream` (22)
- `test_admin_a11y_e2e`: all 7 (ids `#tab-*`/`#panel-*`, `main` inert, `.adm-badge--*`)
- `test_beer_e2e`: all except `test_shortcuts_wait_while_a_dialog_is_open` (19)
- `test_booth_e2e`: all except the 5 listed in D (29). Implementation hooks to keep: `?renderer=canvas2d`, `preview-canvas` must be a `webgl` (WebGL1) context for `test_survives_webgl_context_loss`, the 78 px chip-width assumption in `test_desktop_shows_every_filter`, and CDP touch in `test_switch_filters_by_tap_and_swipe`.
- `test_desktop_e2e`: all 5
- `test_firefox_e2e`: all 3

### D. E2E tests that need rewriting: 19 functions
They depend on SDK module internals, a storage schema or DOM surgery.
- **`test_core_e2e` (4):**
  - `test_camera_capture_upload`, `test_camera_retries_without_resolution_hints`: the probe page imports `/static/core/vb.js` exports; exact gUM constraint shapes.
  - `test_blocked_device_module_does_not_break_the_page`: routes `**/static/core/device.js`.
  - `test_blocked_sdk_shows_a_hint_instead_of_nothing`: routes `**/static/core/vb.js`; `loader.js`.
- **`test_core_ui_e2e` (5):**
  - `test_join_dialog_keeps_the_keyboard_inside`, `test_instagram_dialog_keyboard_scrim_and_focus`: `vb.sheetOpen()`.
  - `test_retry_after_reaches_api_and_upload_errors`: `vb.uploadJpeg`, `vb.api`, `ApiError` fields.
  - `test_fatal_never_shows_raw_script_errors`: `vb.fatal`.
  - `test_in_app_browser_camera_hint_sends_the_guest_out`: `camera.js` `cameraErrorMessage`.
- **`test_admin_upload_controls_e2e` (all 4):** the guest harness is the SNAP page built on `boot`/`mountUserChip`/`uploadJpeg`/`canvasToJpeg` and `err.code`. The admin-side assertions are selector-level.
- **`test_beer_e2e` (1):** `test_shortcuts_wait_while_a_dialog_is_open` removes `.vb-scrim` out-of-band.
- **`test_booth_e2e` (5):**
  - `test_shortcuts_wait_while_a_dialog_is_open` (`.vb-scrim` removal);
  - `test_photo_is_exactly_the_preview` (adds `vb-hidden`, removes `.vb-confetti`, `.vb-flash`, `.vb-toast-host`);
  - `test_unsent_photo_survives_a_reload`, `test_back_button_asks_before_leaving_unsent_photos`, `test_paused_uploads_keep_photos_from_before` (read IndexedDB `vb-booth`/v1/`outbox`/keyPath `id` directly).
- If the rewrite keeps a framework-agnostic SDK at `/static/core/vb.js` and `/static/core/camera.js` with the same exports, plus the same IndexedDB schema, most of D falls back to C.

### Infrastructure changes the rewrite implies
- Add a frontend build step before `pytest -m e2e` and inside `run_webkit.sh`. The Python Playwright image may not include Node/npm, and the repo is mounted read-only and copied, so prebuilding on the host is the simplest option.
- Built output must land where `pages.STATIC_DIR`, `ADMIN_STATIC` and the extension `static_dir`s point, or the blocker and filename tests must be updated.
- Bundler naming must satisfy the blocker-word invariants (section 5), including content hashes.
- No inline styles or inline scripts may appear at runtime under `style-src 'self'` / `script-src 'self'` (no `unsafe-eval`).

### Gaps (behaviour not covered by tests)
- No browser test of identity restore from the localStorage `vb_uid` token after cookies are cleared (only the API-level `uid_token` test).
- No test of the iOS `saveImage` share-sheet path (WebKit runs expect a download).
- Booth filters `neon`, `comic`, `vhs`, `retro`, `emoji`, `colorpop` are checked only for "renders without errors"; there are pixel checks only for bw, party and normal.
- The periodic 30 s upload-state recheck is untested; only `visibilitychange` is.
- Admin UI paging is untested for the audit log (`before`) and the guest list (`next_offset`). The Instagram tab's `recent` thumbnails and per-row copy are untested (`copy-handle` is tested in the lightbox only). Guest search by `#id` is untested in the UI.
- No automated accessibility scan (axe or similar) of guest pages. Keyboard and focus checks exist mainly for core dialogs, the admin, and some beer/booth shortcuts. Admin login has no accessibility or contrast checks.
- Offline (`navigator.onLine=false`) messaging is tested on home only, not on beer/booth.
- The beer in-app-browser hint is tested; the booth equivalent is not.
- There is no "rotate device" hint. Landscape is supported and layout-tested (beer, booth), but no portrait-only behaviour exists or is tested.
- SSE reconnect after a mid-session server restart or network blip is untested; only polling from the start (events route aborted) is.
- No visual regression assertions; all screenshot tests are optional and unasserted.
- No bundle-size or performance budgets, which matter for a TS rewrite.
- The upload progress UI (`onProgress`) is not asserted.
- The `chromium_only` marker is defined but unused.
- WebKit and Firefox are not part of the default run.
