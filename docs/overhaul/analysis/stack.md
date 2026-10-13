# Tech-stack research: decisions (phase 1)

Researched 2026-10-13. Versions are taken from the npm registry and PyPI that
day. Claims were checked in throwaway Vite 8.3.4 builds: bundle sizes,
`<style>`/eval in the actual library code, FastAPI OpenAPI output, and Tailwind
output for older Safari.

## Decisions

| Area | Decision (exact version) |
|---|---|
| Framework | **React 19.3.0** + react-dom 19.3.0, **React Compiler 1.0.0** (babel-plugin-react-compiler) |
| Build | **Vite 8.3.4** (Rolldown/Oxc), @vitejs/plugin-react 6.1.2, @rolldown/plugin-babel 0.2.4, @babel/core 8.0.7 |
| Language | **TypeScript 6.0.3** for `tsc` and the tool APIs; oxlint-tsgolint (TS 7 engine) for fast type-aware lint |
| Pages | Vite **multi-page**: `index.html` (guest), `admin.html` (admin), `gate.html` (static "scan the QR code"). FastAPI serves and gates them server-side. |
| Router | **wouter 3.13.0** (+3 KB; TanStack Router +26 KB, React Router +13 KB) |
| Server state | **@tanstack/react-query 5.104.2** |
| Client state | **zustand 5.0.15** |
| Validation | **zod 4.6.7, imported only as `zod/mini`** (the full import probes `new Function` → CSP violation report). No form library: React 19 actions plus React Aria `Form`. |
| UI primitives | **react-aria-components 1.22.1** (no `<style>` injection, built-in German strings) + @react-aria/optimize-locales-plugin 2.1.0 |
| Styling | **Tailwind CSS 4.3.3** (@tailwindcss/vite 4.3.3) + tailwindcss-react-aria-components 2.2.0 + tailwind-variants 3.3.1 / tailwind-merge 3.7.0; tw-animate-css 1.4.0 optional (pure CSS) |
| CSP styles | **Keep `style-src 'self'`**: no nonce, no `'unsafe-inline'`. React `style={{}}` goes through the CSSOM and is allowed. If a library ever needs it, the escape hatch is a per-request nonce (FastAPI serves every HTML through a route), never `'unsafe-inline'`. |
| Icons / fonts | lucide-react 1.55.0; @fontsource-variable/<family> 5.3.0 (self-hosted) |
| Animation / toasts | CSS only (Tailwind + React Aria `data-entering`/`data-exiting`). Toasts: React Aria `UNSTABLE_Toast*` wrapped in one file. **Banned:** motion/framer-motion, sonner, vaul, @radix-ui/*, emotion, styled-components, bare `zod`. |
| Typed API | **openapi-typescript 7.13.0 + openapi-fetch 0.17.0**; exported `openapi.json` committed; CI drift check; pnpm `peerDependencyRules.allowedVersions: {"openapi-typescript>typescript": "6"}` |
| Lint / format | **oxlint 1.87.0 + oxlint-tsgolint 7.0.2004** (plugins: typescript, react incl. React Compiler rules, jsx-a11y, import, unicorn, oxc, vitest) + **Prettier 3.9.10** + prettier-plugin-tailwindcss 0.8.1. No ESLint (jsx-a11y doesn't support ESLint 10; typescript-eslint requires TS < 6.1). |
| Unit tests | **Vitest 5.0.4** + @testing-library/react 16.3.3 + @testing-library/dom 10.4.2 + happy-dom 21.0.1; optional browser project via @vitest/browser-playwright 5.0.4 + playwright 1.63.0 |
| E2E | **Keep the Python pytest + Playwright 1.63.0 harness**, running against the built `dist` so the real CSP applies. Add axe-playwright-python 0.1.8 (separate context, `bypass_csp=True`, only for axe) and an opt-in Pillow screenshot diff (`-m visual`). |
| Backend | FastAPI 0.143.0, Starlette 1.7.0, pydantic 2.14.1, pydantic-settings 2.15.0, uvicorn 0.54.0, Pillow 12.3.0, segno 1.6.6, tzdata 2026.5, **Python 3.14** |
| DB | **Keep raw sqlite3** and the existing migration runner (`MIGRATIONS` tuple, verbatim). No ORM. |
| Python tooling | uv (`required-version` optional), ruff 0.17.0, mypy 2.4.0 (strict + pydantic plugin), pytest 9.1.1, pytest-xdist 3.8.0, httpx2 2.13.1 |
| Repo | `backend/` (uv project, src layout) + `frontend/` (pnpm). Root keeps the Dockerfile, compose files, Makefile and README. |
| Package manager | **pnpm 11.28.5**: installed locally in ~/.local/bin (via npm; corepack 0.24 is too old), pinned with `packageManager`. Settings live in `pnpm-workspace.yaml`, not `.npmrc`. |
| Task runner | **Make** |
| Node | Build only, never at runtime. Docker uses node:24.21.0-trixie-slim; locally 22.22.1 works (Vitest 5 needs ≥ 22.12). |

## CSP: which libraries inject `<style>`

| Library | Result |
|---|---|
| Radix Dialog/Popover/Select (via react-remove-scroll → react-style-singleton) | **Injects `<style>`.** Excluded. |
| sonner 2.0.8, vaul 1.1.2 | **`__insertCSS` on import.** Excluded. |
| framer-motion / motion 14.1 | AnimatePresence popLayout and view transitions inject `<style>`. Excluded. |
| emotion / styled-components | Inject `<style>`. Excluded. |
| **react-aria-components 1.22.1** | **Clean**: CSSOM only, no eval |
| Base UI 1.9.0 | Injects `<style>` for ScrollArea/Select unless wrapped in `<CSPProvider disableStyleElements>`. Viable alternative. |
| zod 4 full | `new Function("")` probe → CSP violation report. **Use `zod/mini`.** |
| Tailwind 4, React DOM, TanStack, wouter, openapi-fetch, lucide, zustand | Clean |

## Content blockers and Vite naming

- Override every output name; hex hashes only.
- Neutral **source** names too: the dev server serves `/src/...` paths. Keep `sdk/device.ts`; never name a file or folder consent, cookie, track*, analytics, ads, beacon or pixel.
- Always pass `className` to React Aria components so the default `react-aria-*` classes are replaced.
- Load optional modules (device traits, confetti) with `import()` inside try/catch.
- Extend the blocker test to cover:
  - `dist/` file names and `dist/.vite/manifest.json`;
  - `git ls-files frontend/src`;
  - the rendered DOM's class, id and data-testid values.

```ts
// frontend/vite.config.ts (essentials)
import { defineConfig } from 'vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';
import optimizeLocales from '@react-aria/optimize-locales-plugin';

const TARGETS = ['chrome111', 'edge111', 'firefox114', 'safari16', 'ios16']; // Vite 8 default is safari16.4
const api = { target: 'http://127.0.0.1:8000', changeOrigin: false, xfwd: true }; // NOT the string shorthand (changeOrigin:true → CSRF 403)

export default defineConfig({
  plugins: [optimizeLocales.vite({ locales: ['de-DE'] }), react(), babel({ presets: [reactCompilerPreset()] }), tailwindcss(), spaFallback()],
  build: {
    target: TARGETS, cssTarget: TARGETS,
    assetsInlineLimit: 0, manifest: true, sourcemap: false,
    rolldownOptions: {
      input: { guest: 'index.html', admin: 'admin.html', gate: 'gate.html' },
      output: {
        entryFileNames: 'assets/e-[hash].js',
        chunkFileNames: 'assets/c-[hash].js',
        assetFileNames: 'assets/a-[hash][extname]',
        hashCharacters: 'hex',
      },
    },
  },
  server: { port: 5173, strictPort: true, proxy: {
    '/api': api, '/media': api, '/healthz': api,
    '^/[^?]*\\?(?:.*&)?t=': api,
  } },
});
```

## Camera, WebGL, IndexedDB, Share and SSE in React

- The imperative core stays plain TS modules: `renderer.ts`, `filters.ts`, `overlays.ts`, `camera.ts`, `outbox.ts`, `share.ts`.
- A `CameraSession` class owns the video element, the stream, the renderer and the rAF loop, and exposes `setFilter()`, `switchFacing()`, `capture()` (a 1080×1440 Blob from the same shader) and `stop()`.
- React wires only the lifecycle:
  - `useRef` for the video and canvas.
  - One `useEffect([facing])`. Its cleanup **must** cancel rAF, stop the tracks and release WebGL, because StrictMode runs effects twice.
  - Per-frame state never goes into React; the loop reads refs.
  - UI state comes through `useSyncExternalStore(session.subscribe, session.getSnapshot)`.
  - `useEffectEvent` for callbacks.
- Port today's `visibilitychange` restart, webglcontextlost → Canvas2D fallback, and the single reused capture canvas.
- **Outbox:** keep `outbox.ts` as is: IndexedDB `vb-booth`/`outbox` compatibility and the WebKit Blob→ArrayBuffer fallback. Expose the pending count through `useSyncExternalStore`.
- **Share/save:** build the Blob before the tap and call `navigator.share` synchronously in the press handler. React Aria `onPress` fires on pointerup, so verify it in WebKit; fall back to a native `<button onClick>`.
- **Uploads:** keep XHR for progress events.
- **SSE:** one `useAdminEvents()` hook (EventSource → `queryClient.setQueryData`/`invalidateQueries`), plus today's polling fallback.

## Hosting: multi-page build and server gating

| Path | Server behaviour |
|---|---|
| `/` and `/x/{ext}/{rest}` | Access cookie → `index.html` (200, no-cache, CSP). Unknown or disabled extension → 404 page. No cookie → `gate.html` (**404**). |
| `/admin/login` | `admin.html` |
| `/admin/{rest}` | Admin cookie → `admin.html`; otherwise 303 to `/admin/login?next=…` |
| `/assets/{name}` | Public; `Cache-Control: public, max-age=31536000, immutable`; precompressed `.br`/`.gz` by Accept-Encoding, with `Vary: Accept-Encoding` |
| `/api/*`, `/media/*`, `/healthz` | Unchanged |
| anything else | 404 page (the gate page if the visitor has no access) |

- **Client routing:** the guest router covers `/`, `/x/:ext/*`; the admin router uses `<Router base="/admin">`.
- **Dev:** a small `spaFallback()` Vite plugin.
- **Stale chunks:** listen for `vite:preloadError` and reload once (guarded with sessionStorage).
- **Precompression:** `scripts/precompress.mjs` (node:zlib) runs after the build.

## Typed API workflow

1. `uv run virtubooth export-openapi -o ../frontend/openapi.json`: `app.openapi()` works with `openapi_url=None`, so docs stay off at runtime.
2. `pnpm gen:api` runs openapi-typescript → `src/api/schema.gen.ts`.
3. Both files are committed. CI regenerates them and fails on any `git diff`.
4. `src/api/client.ts`: `createClient<paths>({credentials:'same-origin'})` plus an error mapping to `ApiError`. It carries the German message, `retryAfter`, `scan_qr` → gate, and offline vs blocked.
5. SSE: FastAPI 0.143 `fastapi.sse.EventSourceResponse` with a named `AdminEvent` discriminated union (RootModel) so that the event types land in `components`.

Router-level `responses={404/422/429: {"model": ErrorBody}}` replaces the default 422 schema.

## Frontend extensions: static build-time registry

```ts
// src/extensions/booth/index.ts
export default defineExtension({ id: 'booth', load: () => import('./BoothPage') });
// src/extensions/registry.ts
const mods = import.meta.glob<{ default: ExtensionModule }>('./*/index.ts', { eager: true });
```

- The server decides what is enabled (`/api/extensions`); the client renders the intersection.
- A contract test asserts that backend extension ids equal the frontend folders.
- Extensions import only `@/sdk`, `@/ui` and `@/api` (lint rule).

## Backend layout

```
backend/src/virtubooth/
├── __main__.py      # CLI: serve, gen-env, export-openapi
├── app.py           # create_app(settings, extensions=None): composition root
├── settings.py      # pydantic-settings, VB_ prefix, SecretStr, frozen
├── core/            # security, errors (ErrorCode Literal + ApiError), events, ratelimit, logging, clock
├── db/              # database (locked sqlite3), migrations (MIGRATIONS verbatim)
├── repositories/    # users, photos, bans, app_settings, admin_sessions, audit (split repo.py, same SQL)
├── domain/          # frozen dataclasses + constants
├── services/        # identity, uploads, moderation, upload_controls, admin_auth, images, names
├── api/             # deps, schemas/ (pydantic In/Out), routers/
├── web/             # gated HTML entries, /assets immutable + precompressed, gate/404
├── middleware.py    # pure ASGI (no BaseHTTPMiddleware)
├── extensions/      # sdk.py + beer/, booth/
└── tools/           # timelapse, qr, export (keep `python -m virtubooth.tools.<x>`)
```

Also:
- **Gotchas:** `BaseSettings` reads the environment in tests, so clear `VB_*` and pass `_env_file=None`. Never set `FASTAPI_OTEL_AUTO_CONFIGURE`.
- **No `/api/v1`.** Keep today's paths: they are validated against blocker lists and used by e2e.

## Dev workflow

- FastAPI runs on :8000; Vite on :5173 with the object-form proxy (`changeOrigin:false`). Add `VB_ALLOWED_ORIGINS=http://localhost:5173` as a backstop.
- Dev has no CSP (HMR injects `<style>`), so e2e always runs against the built `dist`.

## Docker

```dockerfile
FROM node:24.21.0-trixie-slim AS web   # npm install -g pnpm@11.28.5; pnpm install --frozen-lockfile; pnpm build
FROM ghcr.io/astral-sh/uv:… AS uv
FROM python:3.14-slim AS build         # uv sync (backend/)
FROM python:3.14-slim AS runtime       # ffmpeg, uid 10001, /data, HEALTHCHECK
COPY --from=web /src/frontend/dist /app/web
ENV VB_WEB_DIR=/app/web
```

## CI (GitHub Actions)

Jobs:
- backend: ruff, mypy, pytest
- frontend: oxlint, prettier, `tsc -b`, vitest, build, bundle budgets (guest entry ≤ 150 KB gzip, each activity chunk ≤ 60 KB, admin ≤ 220 KB)
- api-drift
- e2e on Chromium and Firefox
- e2e on WebKit (Playwright container)
- blockers
- docker smoke test

## Risks

- **iOS 16.0–16.3:** set the build and CSS targets to `safari16`/`ios16`; Lightning CSS lowers range media queries. Avoid `@starting-style`.
- **CSP creep:** a lint ban list, plus e2e failing on any console CSP error.
- **Bundle creep:** budgets.
- **StrictMode and WebGL lifecycle:** strict cleanup in every effect.
- **Web Share user activation:** check in WebKit.
- **React Aria Toast is `UNSTABLE_`:** confine it to one file.
- **Toolchain churn:** pin exact versions.
