# Overhaul plan (phase 2)

Inputs:
- [BRIEF.md](BRIEF.md)
- [analysis/architecture.md](analysis/architecture.md): API contract, behaviour inventory, invariants, risks
- [analysis/admin-ui-inventory.md](analysis/admin-ui-inventory.md)
- [analysis/test-suite-map.md](analysis/test-suite-map.md)
- [analysis/ux-audit.md](analysis/ux-audit.md): critique, IA, wireframes, the "Kontaktbogen" design direction, component inventory, copy glossary
- [analysis/stack.md](analysis/stack.md): exact stack, versions, configs

This plan is the contract for every implementation agent. When it and an analysis doc disagree, this plan wins.

## 0. Collision check (requested by the host)

All agents that were running when the overhaul was requested have finished and are merged into `main` (1d6b5eb):
- Firefox/desktop
- blockers
- the three QA-fix branches
- upload pause/stop

The overhaul branches off that state, so their behaviour is the baseline we rebuild:
- upload pause/stop
- join-dialog fixes
- outbox
- the a11y fixes
- blocker-safe names

Their **frontend code** is replaced. Their **backend logic and API tests** survive, refactored. Nothing collides fundamentally.

## 1. Decisions

| Topic | Decision |
|---|---|
| Frontend | React 19.3 + Vite 8.3.4 (multi-page: guest, admin, gate) + TypeScript 6.0.3 strict + React Compiler; wouter; TanStack Query; zustand; `zod/mini`; react-aria-components; Tailwind 4.3; tailwind-variants; lucide-react; @fontsource-variable; openapi-typescript + openapi-fetch; oxlint(+tsgolint) + Prettier; Vitest 5. Exact versions are in analysis/stack.md. |
| Backend | FastAPI kept and restructured into `backend/src/virtubooth` (layers: core, db, repositories, domain, services, api, web, extensions, tools). Pydantic response models on every route, pydantic-settings, `ErrorCode` literal enum, typed SSE events, `export-openapi` CLI. Raw sqlite3 and the migration runner stay. |
| Design | **"Kontaktbogen"** from the UX audit, §6A. Guests and the live screen: dark "Rotlicht" with an amber "Safelight" accent. Manage: a light "Leuchttisch". Grease-pencil marks (X = hidden, circle = selected). Signature element: **the film edge** (Filmrand) with frame numbers, which doubles as the upload progress track. "Develop" motion. Fonts: Bricolage Grotesque (UI/display) + Doto (large numerals only). Lucide icons replace all emoji in UI chrome; emoji may stay inside photo overlays and filter art. |
| Copy | The glossary in UX audit §3.4 is binding: Ausblenden/Einblenden, Löschen…, Hochladen, Erneut senden, Noch ein Bier, Neues Foto, Seite neu laden, Start, Hochladen pausiert, Hochladen für alle stoppen, Gesperrt / Automatisch gesperrt, Instagram-Name, Gerätemerkmal, Speichern / Herunterladen. German typography: „…“, `…`, NBSP, tabular figures. |
| CSP | Unchanged and strict: `script-src 'self'`, `style-src 'self'`. Libraries that inject `<style>` or use eval are banned (stack.md list). Every e2e test fails on console errors, as it does today. |
| Content blockers | Neutral names in source paths, built assets (hex-hash names), classes, ids and test ids. The blocker test is extended to cover `dist/` and `frontend/src`. API paths stay as they are. |
| API paths | Unchanged, no `/api/v1`. Response shapes may gain fields but never lose them silently: e2e and API tests define them. |
| Tests | Python pytest stays the backend and e2e oracle. It moves to `backend/tests`, and e2e runs against the built `frontend/dist`. Frontend unit tests use Vitest. The old DOM-based e2e tests are moved to `backend/tests/e2e_legacy/` (not collected; removed after the overhaul) as a reference while the new UI's e2e tests are written. |
| Push | Never. Everything stays on local branch `overhaul`. |

### Scope: new product features (from the UX audit)

In scope, all small, high value:
1. **Never lose a shot.** The Beer Cam gets the same IndexedDB outbox as the Fotobox. When uploads are paused or stopped, the shutter explains this up front instead of letting the guest shoot and discarding the photo.
2. **"Deine Bilder"** on the start screen: a new `GET /api/me/photos` returns the guest's own visible photos.
3. **One toast slot**, the **guest pass** (identity plus status), and the **activity switcher**.
4. **Admin**:
   - live: dense 2-column grid, a 44 px hide toggle, an undo toast, a phone bottom bar;
   - manage on desktop: sidebar, dense contact sheet, inspector panel, data tables;
   - user page: status line, two actions, ban in a sheet, technical details collapsed;
   - deep links via `?photo=`.
5. **Export section in manage**: archive download, timelapse job with progress, QR sheet, as background jobs that reuse the existing tools.
6. **Instagram board**: a ZIP of photos per handle, and an "Erledigt" mark per handle.

Out of scope:
- a service worker / offline shell;
- the Live Wall (the extension interface keeps the door open);
- multi-worker;
- an ORM.

## 2. Target repo layout

```
virtubooth/
├── backend/
│   ├── pyproject.toml  uv.lock  .python-version
│   ├── src/virtubooth/
│   │   ├── __main__.py            CLI: serve | gen-env | export-openapi
│   │   ├── app.py                 create_app(settings, extensions=None): composition root
│   │   ├── settings.py            pydantic-settings (VB_*), incl. VB_WEB_DIR
│   │   ├── core/                  security, errors, events, ratelimit, logging, clock
│   │   ├── db/                    database, migrations (MIGRATIONS verbatim + new steps appended)
│   │   ├── domain/                dataclasses + constants (PHOTO_W/H, AUTO_BAN_REASON, PAUSE_*)
│   │   ├── repositories/          users, photos, bans, app_settings, admin_sessions, audit, admin_read_models
│   │   ├── services/              identity, uploads, moderation, upload_controls, admin_auth, exports, instagram, images, names
│   │   ├── api/                   deps, schemas/, routers/ (guest, uploads, media, extensions, admin/*)
│   │   ├── web/                   gated HTML entries from VB_WEB_DIR, /assets (immutable, precompressed), gate/404
│   │   ├── middleware.py          pure ASGI
│   │   ├── extensions/            sdk.py (Extension, UploadPolicy, UploadContext, discover), beer/, booth/ (filters.json lives here)
│   │   └── tools/                 timelapse, qr, export (keep `python -m virtubooth.tools.<x>`)
│   └── tests/
│       ├── conftest.py  unit/ … api/ …  fixtures/ (blocker rules, web stubs)
│       ├── e2e/                   conftest.py (live server serving frontend/dist, fake cameras, browsers), run_webkit.sh
│       └── e2e_legacy/            old DOM tests, NOT collected (reference only, deleted in wave 4)
├── frontend/
│   ├── package.json  pnpm-lock.yaml  pnpm-workspace.yaml  .node-version
│   ├── index.html  admin.html  gate.html  vite.config.ts  tsconfig*.json  .oxlintrc.json  .prettierrc
│   ├── openapi.json               generated, committed
│   ├── public/                    boot-check.js (today's loader.js), icon.svg
│   ├── scripts/precompress.mjs
│   └── src/
│       ├── api/                   schema.gen.ts (generated), client.ts, errors.ts, events.ts, types.ts (aliases)
│       ├── ui/                    design system: React Aria + Tailwind components (no app logic)
│       ├── styles/                app.css (@theme tokens), fonts
│       ├── sdk/                   guest runtime used by guest pages + extensions (see §4)
│       ├── guest/                 guest entry: main.tsx, routes, Home, JoinSheet, gate pieces
│       ├── admin/                 admin entry: main.tsx, routes, Login, Live, Manage/*, User, Export, useAdminEvents
│       ├── extensions/            registry.ts, beer/, booth/
│       └── lib/                   format.ts (de-DE), messages.de.ts
├── docs/  (ARCHITECTURE.md rewritten, DEPLOY.md, overhaul/)
├── .github/workflows/ci.yml
├── Dockerfile  .dockerignore  compose.yaml  docker-compose.coolify.yaml   (root: Coolify points here)
├── Makefile  README.md  .editorconfig  .gitignore
```

No barrel `index.ts` files, except where noted: import from concrete module paths so parallel agents never fight over a shared index.

## 3. Backend plan

### Refactor (wave 1, agent BE-core)
- Move `virtubooth/` → `backend/src/virtubooth/`, `tests/` → `backend/tests/`, and `pyproject.toml`, `uv.lock` and `.python-version` → `backend/`.
- Split `repo.py` per aggregate (same SQL).
- Move business logic out of routers into services:
  - the upload pipeline, join, and ban / auto-ban release;
  - services own transactions, audit and event publishing.
- Make audit writes atomic with the change they record.
- Pydantic `*Out` response models for every route, built `from_attributes`. Delete `guest_view` / `admin_view` from the dataclasses.
- `ErrorBody {error: ErrorCode, message: str}` with `ErrorCode` a `Literal` of every code, declared through router-level `responses`.
- SSE via `fastapi.sse.EventSourceResponse` with an `AdminEvent` discriminated union (RootModel). The same payloads and event names as today, plus a consistent `auto_banned` field on user refs.
- `settings.py` with pydantic-settings: same env names and validators, plus:
  - `VB_WEB_DIR` (default `<repo>/frontend/dist` when present);
  - `VB_DEV` (dev mode; relaxes nothing security-relevant, only for the stub web dir);
  - allowed origins stay.
- `export-openapi` CLI command writes deterministic JSON (`sort_keys`, indent 2).
- `web/` serving per stack.md "Hosting":
  - multi-page entries, `/assets` immutable with precompressed variants;
  - the gate (404) and notfound (404) pages come from the built `gate.html` (the notfound variant is a query/hash state or the same file with a different message: decide and document);
  - admin 303 with `next`;
  - `/x/<id>` 308.
- Unit tests that request HTML use a stub web dir fixture (`tests/fixtures/web/`).

### Fix these known bugs (from the analysis)
1. **SSE overflow:** the orphaned queue keeps the stream alive with no events. Close the stream so the client reconnects; optionally add a `Last-Event-ID` replay ring buffer (small).
2. **Admin pages miss events** between the first fetch and the SSE open: subscribe first, or replay.
3. **Audit atomicity.**
4. **`delete_photo` unlinks before COMMIT:** unlink after commit.
5. **`user.uploads_changed` lacks `auto_banned`:** make user refs consistent everywhere.
6. **`next` cursor non-null on an exactly full page:** fix with limit+1.
7. **`PATCH /api/me` for banned users:** allow editing the Instagram name? No. Keep it refused, but with the message "Dieses Gerät ist gesperrt." (not about uploads).
8. **`login_locked` lacks `Retry-After`:** add it.

### New endpoints (contract; BE-core builds 1, BE-features builds 2–4)
1. **`GET /api/me/photos`** (guest)
   - Returns `{photos: GuestPhoto[]}`: the caller's own non-deleted, non-hidden photos, newest first, limit 60.
   - `GuestPhoto = {id, extension, seq, created_at, width, height, url, thumb_url}`.
2. **Exports** (admin):
   - `POST /api/admin/exports {kind: "archive"|"timelapse"|"qr", options?}` → `202 {job: ExportJob}`
   - `GET /api/admin/exports` → `{jobs: ExportJob[]}`
   - `GET /api/admin/exports/{id}/download` → the file (attachment)
   - `DELETE /api/admin/exports/{id}`

   **ExportJob** `{id, kind, status: "queued"|"running"|"done"|"failed", progress: number|null, created_at, started_at, finished_at, error: string|null, file_name, bytes}`.

   **Options per kind:**
   - archive: `{include_hidden: bool, include_db: bool}`
   - timelapse: `{extension: str="beer", fps: int, crossfade: bool, include_hidden: bool}`
   - qr: `{base_url?: str}`, defaulting to `VB_PUBLIC_BASE_URL`. The output is a zip with the SVGs/PNGs and `qr-sheet.html`.

   **Runtime and events:**
   - Jobs run one at a time in a worker thread and reuse the `tools/` functions; outputs go to `<data>/exports/`.
   - Event `export.updated {job}`.
   - Job state persists in the settings KV or a new table via migration step 3; the agent decides and documents. A restart marks running jobs as failed.
3. **Instagram:**
   - `GET /api/admin/instagram` gains `done: bool` per handle.
   - `POST /api/admin/instagram/{handle}/done {done: bool}` stores the mark (settings KV), audit-logged.
   - `GET /api/admin/instagram/{handle}/photos.zip` streams a ZIP of that handle's visible photos; non-banned guests only.
4. **Admin photo deep link:** `GET /api/admin/photos/{id}` already exists, which is enough for `?photo=`.

## 4. Frontend plan

### Apps
- **Guest** (`index.html` → `src/guest/main.tsx`):
  - routes `/` (Start) and `/x/:ext/*` (extension, lazy);
  - gate and notfound states are server-rendered from `gate.html`.
- **Admin** (`admin.html` → `src/admin/main.tsx`):
  - routes `/admin/login`, `/admin/live`, `/admin/manage` (sections via `?tab=` as today, plus `export`), `/admin/user?id=`;
  - React Query plus `useAdminEvents()`.
- **Gate** (`gate.html`): static. Optional tiny script with a context-aware message (in-app browser hint). It must work with no JS.
- **`public/boot-check.js`**: today's `loader.js`, a classic script. Every HTML entry includes it **before** the module script, as `<script src="/boot-check.js" defer>`. The app sets `window.__vbReady = true` on boot.

### Module ownership and interfaces (so wave-2 agents don't collide)

**`src/ui/*` — FE-foundation:**
- presentational React Aria + Tailwind components only;
- wave-2 agents may ADD new files under `src/ui/` but must not edit existing ones; they report needed changes instead.

**`src/api/*` — FE-foundation; wave 2 regenerates the schema:**
- `client.ts` exports `api` (openapi-fetch client) and `ApiError`:
  - `.status`, `.code`, `.message` (German), `.retryAfter?`, `.offline`;
  - `unwrap(res)` maps errors;
  - `scan_qr` → `location.reload()`.
- `types.ts` holds the friendly aliases (`GuestUser`, `AdminPhoto`, …) from `schema.gen.ts`.

**`src/sdk/` — wave 2, split between two agents:**

GP (guest platform) owns:
- `session.ts`:
  ```ts
  export type SessionState =
    | { status: 'loading' }
    | { status: 'needs_join'; join: JoinInfo }
    | { status: 'ready'; user: GuestUser; uploadsStopped: boolean }
    | { status: 'banned'; user: GuestUser }
    | { status: 'error'; error: ApiError };
  export function useSession(): SessionState;
  export function refreshSession(): Promise<void>;
  export function joinParty(input: { instagram: string | null }): Promise<void>;
  export function setInstagram(handle: string | null): Promise<GuestUser>;
  export function canUpload(s: SessionState): { ok: true } | { ok: false; reason: 'paused' | 'stopped' | 'banned' | 'not_ready'; message: string };
  ```
- `device.ts`: device traits, loaded via `import()` with a fallback; the name stays neutral.
- `feedback.ts`: vibrate, flash, develop, confetti-free.
- `platform.ts`: isIOS, isInAppBrowser.
- `debug.ts`: `?debug=1`, collapsible, `pointer-events: none`.
- `share.ts`: `saveImage(blob, name)`.
- `components/`:
  - `GuestPass.tsx`;
  - `ActivityMenu.tsx`;
  - `StatusSlot.tsx`;
  - `ActivityShell.tsx`, the page frame for extensions. Its slots are `title`, `topRight` (GuestPass by default), `stage`, `filmEdge`, `hint` and `controls`, and the toast slot is positioned above `controls`.

AC (activities) owns:
- `camera/`: `session.ts` (CameraSession), `renderer.ts`, `filters.ts`, `overlays.ts`, `capture.ts` (crop math), `errors.ts` (cameraErrorMessage);
- `upload.ts`: `uploadPhoto(ext, blob, {meta, onProgress, signal}) => Promise<UploadResult>` (XHR);
- `outbox.ts`: shared IndexedDB outbox, compatible with the existing `vb-booth` DB:
  - `addToOutbox`, `flushOutbox`, `useOutbox()` → `{pending, items}`;
  - the activity id is stored per item;
- `extensions/beer/**`, `extensions/booth/**`, `extensions/registry.ts`.

**`src/guest/*` — GP:** main.tsx, routes, Home ("Deine Bilder", activity cards with live lines), JoinSheet, the Du-sheet (identity + Instagram), notices.

**`src/admin/*` — AD (admin agent):** everything admin, including the Export and Instagram board UIs against the §3 contract. Until BE-features merges, use the generated types once available, or a local `types.pending.ts` deleted after merge.

**`src/lib/*` — FE-foundation:** format (de-DE dates, relative time, `1 Mio.`, NBSP), messages.de.ts (shared error texts, glossary).

### Design system (FE-foundation)

**Image-first, adapted from the image-to-code skill.** There is no image model here, so the agent first renders static mockups of the key screens with the Kontaktbogen tokens, screenshots them with Playwright, critiques them against frontend-design and web-design-guidelines, and iterates. Only then does it build the real components.

The key screens are the wireframes in UX audit §5:
- phone Start
- Beer Cam
- Fotobox
- result print
- admin live on phone
- manage on desktop
- user page
- upload-controls sheet

Mockups and screenshots go to `docs/overhaul/design/`.

**Tokens:**
- palette: Kamera-Schwarz, Rotlicht, Safelight, Leuchttisch, Negativ-Blau, Fettstift + muted variants, with contrast documented;
- type scale 13/15/17/21/27/34/44 + Doto 22/28/160; weights 400/600/760;
- spacing 4…48; radii 0/10/full;
- z-layers named;
- motion durations, plus reduced-motion.

**Components:** the UX audit §7 inventory, including the film edge (`FilmEdge`), Shutter, Countdown, FilterCarousel shell, PhotoTile, Sheet, ConfirmDialog, Toast (single slot), Notice, Switch, Segmented, TextField with "@" prefix, Badge, DataTable, SidebarNav/BottomBar, ConnectionIndicator, EmptyState, Skeleton, Help disclosure.

**A UI gallery page** for dev only (`/admin/__ui`?). Must not ship in prod bundles; a separate dev entry `ui.html` is excluded from the build input.

### Test ids
Keep today's `data-testid`s for concepts that still exist (join, tile-*, shutter, user-chip→guest-pass, consent sheet ids, admin ids from admin-ui-inventory.md) where reasonable, so the ported e2e tests stay recognizable. New UI pieces get neutral test ids.

## 5. Testing plan

- **Backend:** all API/unit tests stay green through the refactor; they move, they aren't rewritten. Add tests for the new endpoints and bug fixes.
- **Frontend:** Vitest tests for:
  - sdk logic: api error mapping, outbox, camera crop math, facing/mirroring rules, meta encoding, session state machine;
  - lib/format;
  - key components (Testing Library).
- **e2e:**
  - Each wave-2 agent writes the e2e tests for its area in `backend/tests/e2e/`, porting the relevant legacy tests (see test-suite-map.md) to the new UI: same behaviours, new selectors.
  - The harness serves the **built** frontend (`make build-web`, or a fixture that builds once per session if `frontend/dist` is stale).
  - Zero console errors: CSP, React, failed loads other than the expected ones.
- **Cross-browser:** Chromium + Firefox in waves 2 and 3, WebKit via `run_webkit.sh` (updated for the new layout) in wave 3.
- **Blockers:** extend `test_core_blockers.py` to `frontend/dist` and `frontend/src` names, plus a rendered-DOM scan in e2e.
- **A11y:** axe (axe-playwright-python) over the main screens in wave 3; serious and critical findings = 0.

## 6. Waves and agents

### Wave 1 (parallel)
- **BE-core.** Backend restructure + refactor + bug fixes + `/api/me/photos` + web serving + `export-openapi` + test move.
  - Owns: `backend/**`, deleting the old root `virtubooth/` and `tests/`, root `pyproject.toml` / `uv.lock` / `.python-version`, and minimal path fixes in Dockerfile / .dockerignore / compose.
  - Done when: all API/unit tests pass under `backend/`; the e2e harness is moved and adapted (legacy DOM tests in `e2e_legacy/`); `export-openapi` works; the web module serves a stub dist correctly (gate 404, notfound 404, admin redirect, assets caching); ruff + mypy clean (mypy strict where feasible; document exceptions).
- **FE-foundation.** Frontend scaffold, toolchain, design tokens, mockups (image-first), the UI component library + gallery, `api/client.ts` + error mapping (typed against a provisional schema exported from the current code, regenerated later), `lib/format.ts` + `messages.de.ts`, the skeleton folders and stub modules for the wave-2 interfaces (§4) with the exact exported names and TODO bodies, and `boot-check.js`.
  - Owns: `frontend/**` and `docs/overhaul/design/**`.
  - Done when: `pnpm lint`, `pnpm typecheck`, `pnpm test` and `pnpm build` are green; the build output has neutral names; the gallery screenshots have been reviewed.

### Wave 2 (parallel, after wave 1 merges and the schema is regenerated)
- **GP: guest platform.** sdk/session, device, feedback, platform, debug, share, components/*; guest app (Start, Deine Bilder, JoinSheet, Du-sheet, notices); gate.html; guest e2e (join, home, gate, chip/instagram, blockers fallback, loader hint, two tabs, small phones).
- **AC: activities.** sdk/camera/*, upload, outbox, beer + booth extension pages, registry; e2e for beer and booth. Port the legacy tests: WYSIWYG, exact size, filters, countdown, outbox, landscape, desktop webcam, keyboard, paused/stopped/banned, rate limit, camera errors.
- **AD: admin.** The whole admin app: login, live, manage (photos, guests, Instagram board, bans, log, export), user page, upload controls, lightbox/inspector, events; admin e2e + a11y tests.
- **BE-features.** Export jobs + Instagram done/zip endpoints + tests. Owns only new backend files plus minimal registration lines.
- RAM limit: run at most 3 browser-heavy agents at once. BE-features is light.

### Wave 3: integration
- **INT.** Dockerfile multi-stage (Node build stage → Python runtime with `VB_WEB_DIR`), compose files, Makefile, `.github/workflows/ci.yml`, run_webkit.sh, blocker test extension, axe tests, README + ARCHITECTURE.md + DEPLOY.md rewrites. Cross-browser fixes go back to the owning areas, or INT fixes small ones.

### Wave 4: verification
- **QA** walkthrough (report only, all browsers and viewports, compared with the UX audit's screenshots).
- **Security review** of the delta: new endpoints, web serving, CSP with the new bundle, export downloads.
- **Fix agents** for the findings.
- Delete `e2e_legacy/` (done: removed after the overhaul).
- Final full runs: unit, Chromium, Firefox, WebKit, Docker smoke, blockers with the full lists.

### Wave 5: report
`docs/overhaul/REPORT.md` plus a chat summary, written for the host.

## 7. Rules for every agent

- Work in your own worktree branched off `overhaul`. Commit in logical steps, with commit messages ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Never touch the main checkout or port 8000.
- Stay inside your ownership. If you need a change elsewhere, work around it and list it in your report.
- Use the skills: read `~/.claude/skills/<name>/SKILL.md`:
  - frontend-design and web-design-guidelines for any UI work;
  - awesome-design for style references;
  - image-to-code (mockups first) for design work;
  - playwright-cli and webapp-testing for browser checks.
- Screenshots: LOOK at them. Phone 390×844, small 360×640, landscape 844×390, desktop 1440×900.
- Keep the invariants in BRIEF.md. When in doubt, analysis/architecture.md §2–§5 describes the current behaviour that must survive.
- Exact pinned versions; no new dependency outside stack.md without a reason written in your report.
