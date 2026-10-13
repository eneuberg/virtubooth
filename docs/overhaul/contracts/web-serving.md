# Contract: how the backend serves the built frontend

Owner: BE-core (wave 1). Audience: FE-foundation, GP, AC, AD (waves 1 and 2), INT (wave 3).
Code: `backend/src/virtubooth/web/` (`frontend.py`, `routes.py`); tests:
`backend/tests/api/test_web.py`, `backend/tests/unit/test_frontend_contract.py`.

## 1. What the build must contain

`VB_WEB_DIR` (default: `<repo>/frontend/dist` when it exists; Docker: `/app/web`
from wave 3 on) must hold:

| File | Role |
|---|---|
| `index.html` | the guest app (Start, `/x/<ext>/…`) |
| `admin.html` | the admin app (`/admin/…`, including `/admin/login`) |
| `gate.html` | static page for **both** "no access" (gate) and "not found"; must work without JS |
| `assets/**` | hashed build files (`e-<hash>.js`, `c-<hash>.js`, `a-<hash>.<ext>`), optionally with `.br` / `.gz` siblings |
| other root files | public, e.g. `boot-check.js`, `icon.svg` |

The server refuses to start when the directory or one of the three HTML files is
missing, unless `VB_DEV=1`: then it serves built-in placeholder pages (CSP-clean,
no JS) and the API works normally. Use that for `pnpm dev` on :5173 (Vite proxies
`/api`, `/media`, `/healthz` and `?t=` entries to :8000, see stack.md).

Every HTML entry must be CSP-clean (no inline `<script>`/`<style>`, no `style=`,
no `on*=`, no external URLs, `<html lang="de">`) and load `/boot-check.js`
(classic, `defer`) before the module script. The apps set `window.__vbReady = true`
once booted; the e2e smoke tests wait for it.

## 2. The gate / not-found placeholder (no script needed)

`gate.html` contains the attribute **`data-vb-mode="gate"` exactly once**, on
`<html>`. It contains the markup for both messages; CSS shows one of them:

```html
<html lang="de" data-vb-mode="gate">
  …
  <main data-testid="gate">
    <section class="when-gate"><h1>Scan den QR-Code</h1>…</section>
    <section class="when-notfound"><h1>Hier ist nichts</h1>…</section>
  </main>
```

```css
html[data-vb-mode="gate"] .when-notfound,
html[data-vb-mode="notfound"] .when-gate { display: none; }
```

The server answers **404** in both cases and:

- gate: sends the file unchanged, header `X-VB-Page: gate`;
- not found: replaces the first `data-vb-mode="gate"` with
  `data-vb-mode="notfound"`, header `X-VB-Page: notfound`.

Keep the texts "Scan den QR-Code" and "Hier ist nichts" (or tell BE/QA when
the copy changes: tests and the old e2e suite look for them). Class names must
stay blocker-neutral (no `notice`, `banner`, `popup`, `overlay`, …). An optional
script may refine the message (in-app browser hint); the page must not need it.

## 3. Routes

| Path | Answer |
|---|---|
| `GET /` | access cookie → `index.html` (200); else gate (404) |
| `GET /?t=<token>` (any page path) | valid → 303 to the same URL without `t`, sets `vb_access`; invalid → gate (404) |
| `GET /x/<id>` | 308 → `/x/<id>/` |
| `GET /x/<id>/<route…>` | no access → gate (404); unknown or disabled extension → not found (404); a route segment starting with `.` → not found; else `index.html` (200) |
| `GET /admin`, `/admin/` | 303 → `/admin/live` |
| `GET /admin/login` | `admin.html` (200), public |
| `GET /admin/<route…>` | admin session → `admin.html` (200); else 303 → `/admin/login?next=<quote(path?query, safe="/")>`, e.g. `next=/admin/user%3Fid%3D5` |
| `GET /assets/<file>` | public; see §4 |
| `GET /<file>` | a root file of the build (not the HTML entries), public, `Cache-Control: public, max-age=300` |
| anything else | not found (404), or the gate (404) without access |
| `/api/*`, `/media/*`, `/healthz` | the API (JSON errors, never HTML) |

The admin app routes itself under `/admin` (`<Router base="/admin">`); the
server does not know the admin routes, any path gets `admin.html`. The login
page must validate `next` (only `/admin/<page>` with an optional `?…`, never an
absolute URL or `//…`) before following it.

## 4. Caching and compression

| What | Cache-Control |
|---|---|
| HTML (entries, gate) | `no-cache` (+ `ETag`) |
| `/assets/*` | `public, max-age=31536000, immutable`, `Vary: Accept-Encoding` |
| root files | `public, max-age=300` |
| `/api/*` | `no-store` (also the SSE stream) |
| `/media/*` | `private, max-age=86400` |

For `/assets/<file>` the server sends `<file>.br` (`Content-Encoding: br`) or
`<file>.gz` (`gzip`) when the client accepts it (q-values honoured, br first),
with the original's `Content-Type`. The `.br`/`.gz` URLs themselves are 404.
So `scripts/precompress.mjs` should write the siblings next to each asset.

## 5. Safety

- Paths are resolved inside `VB_WEB_DIR` only; `..`, NUL, backslashes and every
  path segment starting with `.` are refused (404). `.vite/manifest.json` is never
  served.
- All responses carry the strict CSP (`script-src 'self'; style-src 'self'; …`),
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP/CORP, etc.
- File names of the build must not match
  `fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]`
  (hashes included: use hex hashes). `backend/tests/unit/test_core_blockers.py`
  checks `frontend/dist` when it exists.

## 6. For the e2e suite

`backend/tests/e2e/conftest.py` serves `frontend/dist` (or `VB_E2E_WEB_DIR`) from
a live uvicorn and skips every e2e test when there is no build. Build first:
`cd frontend && pnpm build`, then `cd backend && uv run pytest -m e2e`.
