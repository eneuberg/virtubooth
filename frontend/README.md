# virtubooth frontend

React 19 + TypeScript 6 + Vite 8, built as a multi-page app with three
entries: the guest app (`index.html`), the admin app (`admin.html`) and the
static gate page (`gate.html`). The backend serves the build (`dist/`); there
is no separate frontend server in production. Architecture:
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#frontend). Design system:
[docs/overhaul/design/DESIGN.md](../docs/overhaul/design/DESIGN.md).

## Setup

Node 22.22.1 (`.node-version`) and pnpm 11.28.5 (`packageManager`). Corepack
cannot run pnpm 11, so install it with npm:

```sh
npm install -g pnpm@11.28.5
pnpm install --frozen-lockfile     # also applies patches/react-aria@3.53.1.patch
```

pnpm 11 reads its settings from `pnpm-workspace.yaml`: exact versions only
(`savePrefix: ''`), the minimum release age exceptions, and
`patchedDependencies`. No dependency needs an install script.

## Scripts (run in `frontend/`)

| Script               | What                                                                                                                                                                                                                                         |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pnpm dev`           | Vite on :5173 with hot reload. It proxies `/api`, `/media`, `/healthz` and `?t=` token entries to the backend (`VB_API_URL`, default `http://127.0.0.1:8000`; run `make dev` there). Open `/?t=<token>`; the component gallery is at `/__ui` |
| `pnpm build`         | `vite build` into `dist/`, then `scripts/precompress.mjs` (`.br`/`.gz` next to every asset) and `scripts/check-names.mjs` (fails on content-blocker-prone names)                                                                             |
| `pnpm build:gallery` | the dev-only UI gallery into `dist-gallery/` (never shipped)                                                                                                                                                                                 |
| `pnpm serve:dist`    | `scripts/serve-dist.mjs [dir] [port]`: serves a build with the production security headers (CSP) on :4310, without the backend                                                                                                               |
| `pnpm lint`          | oxlint (type-aware, warnings are errors) + `prettier --check`                                                                                                                                                                                |
| `pnpm fmt`           | Prettier with the Tailwind class sorter                                                                                                                                                                                                      |
| `pnpm typecheck`     | `tsc -b` (strict, `noUncheckedIndexedAccess`, …)                                                                                                                                                                                             |
| `pnpm test`          | Vitest on happy-dom (unit and component tests, `src/**/*.test.ts(x)`)                                                                                                                                                                        |
| `pnpm gen:api`       | `openapi.json` → `src/api/schema.gen.ts` (openapi-typescript)                                                                                                                                                                                |

`scripts/browser-check.py` opens pages of a running build in Chromium at
phone and desktop sizes. It reports console errors (CSP), sideways overflow
and blocker-prone class names, and takes screenshots:

```sh
pnpm build && pnpm serve:dist &
uv run --project ../backend python scripts/browser-check.py http://127.0.0.1:4310 /tmp/shots / /admin/login /gate
```

The end-to-end tests live in the backend (`backend/tests/e2e`) and run
against `dist/`: `make e2e` from the repository root.

## Structure (`src/`)

| Folder        | What                                                                                                                                                                                 | Notes                                                       |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| `api/`        | `client.ts` (openapi-fetch + `unwrap`), `errors.ts` (`ApiError`, German messages), `events.ts` (the admin SSE stream), `types.ts` (friendly type names), `schema.gen.ts` (generated) | import types from `types.ts`, never from the generated file |
| `ui/`         | the design system: presentational React Aria + Tailwind components (`Button`, `Sheet`, `Toast`, `FilmEdge`, `Shutter`, `DataTable`, `PhotoTile`, …)                                  | no API calls, no app state                                  |
| `styles/`     | `app.css`: Tailwind 4 `@theme` tokens, surfaces, fonts, animations; `contrast.test.ts`                                                                                               | the only source of colours, sizes, radii                    |
| `sdk/`        | the guest runtime: `session.ts`, `camera/`, `upload.ts`, `outbox.ts`, `status.ts`, `components/` (`ActivityShell`, `GuestPass`, `ActivityMenu`, …)                                   | what activities build on                                    |
| `guest/`      | the guest app: `main.tsx`, routes, Start, JoinSheet, "Deine Bilder", the photo viewer                                                                                                |                                                             |
| `admin/`      | the admin app: login, live, manage (photos, guests, Instagram, bans, log, export), user page, upload controls, `store/` (React Query + the event stream)                             |                                                             |
| `extensions/` | `registry.ts` + one folder per activity (`beer/`, `booth/`), each with an `index.ts`                                                                                                 | the folder name is the backend's extension id               |
| `lib/`        | `format.ts` (de-DE numbers, dates, frame labels, NBSP), `messages.de.ts` (the glossary and shared texts), `boot.ts`                                                                  | all copy and numbers go through here                        |
| `gallery/`    | the dev-only component gallery (`ui.html`)                                                                                                                                           | not a build input of `dist/`                                |

Imports use the `@/` alias (`@/sdk/session`) and concrete module paths: there
are no barrel `index.ts` files, except the extension registrations.

## Conventions

- **CSP: `script-src 'self'; style-src 'self'`.** Nothing may inject a
  `<style>` element, use `eval` or `new Function`, set a `style` attribute as
  markup (`setAttribute('style')`, `dangerouslySetInnerHTML`) or load anything
  from another host. React's `style={{…}}` is fine: it goes through the
  CSSOM. Libraries that inject styles are banned in `.oxlintrc.json`
  (sonner, vaul, motion, framer-motion, styled-components, Radix, Emotion,
  react-remove-scroll, and bare `zod`: use `zod/mini`, because the full build
  probes `new Function`). Every e2e test fails on a console error, so a CSP
  violation fails the suite.
- **The React Aria patch.** react-aria 3.53.1 injects two `<style>` elements
  at runtime: in `usePress` (on every pressable) and in `usePreventScroll` on
  iOS (every open modal). The CSP blocks both.
  `patches/react-aria@3.53.1.patch` removes them, and `app.css` carries the
  same rules (`touch-action` on `[data-react-aria-pressable]`,
  `overscroll-behavior` under `html[data-vb-scroll-lock]`). pnpm applies the
  patch on install, the Dockerfile copies `patches/` before installing, and
  any react-aria update needs the patch checked again.
- **The locale pin.** `@react-aria/optimize-locales-plugin` keeps only de-DE
  strings in the bundle, so every app root wraps in `<UiProvider>`, which pins
  `I18nProvider locale="de-DE"`. Without it React Aria crashes on an English
  phone.
- **Neutral names** for content blockers, in file names, CSS classes, ids,
  test ids and storage keys. Avoid consent, cookie, gdpr, banner, notice,
  modal, backdrop, privacy, popup, advert, fingerprint, track, beacon and
  `ad(s)`; for example the full-screen state is `vb-screen` and overlays are
  `vb-scrim`. Built assets are hex-hashed (`assets/e-<hash>0.js`, with the
  trailing `0` so a hash can never end in "ad"). `pnpm build` fails on a bad
  name.
- **Tokens only.** Colours, type sizes, weights, spacing, radii, z-layers and
  durations come from `app.css` (see DESIGN.md). Components use the
  semantic colours (`surface`, `ink`, `accent`, `danger`, …), which flip with
  `data-surface="dark|light"`. No new colours, sizes or radii.
- **German UI.** Copy comes from `lib/messages.de.ts` (the binding glossary:
  "Ausblenden", "Hochladen", "Erneut senden", "Noch ein Bier", …) and every
  number or date from `lib/format.ts`. Typography: „…“, `…`, NBSP before
  units, tabular figures, no caps eyebrows, Lucide icons instead of emoji in
  the chrome.
- **One toast slot per page** (`ui/Toast`), `className` on every React Aria
  element (no `react-aria-*` default classes), 44 px touch targets, and
  `window.__vbReady = true` once an app has rendered (`lib/boot.ts`
  `markReady()`): `public/boot-check.js` explains a page that never starts.
- **`public/` is an allow-list on the server.** Without the party cookie the
  backend serves only the root files listed in `PUBLIC_ROOT_FILES`
  (`backend/src/virtubooth/web/frontend.py`): `boot-check.js`, `gate-hint.js`,
  `icon.svg`, `favicon.ico`, `apple-touch-icon.png`, `robots.txt`. Any other
  root file is a 404, so a new file in `public/` that must be reachable needs
  an entry there. Everything Vite bundles goes to `assets/` and needs nothing.
- **Browser targets:** Chrome/Edge 111, Firefox 114, Safari and iOS 16
  (`vite.config.ts`).
- **Versions are exact** (`package.json`, no ranges). A new dependency needs a
  reason and a CSP check against a built `dist/` (`scripts/browser-check.py`).

## Adding an activity

A folder `src/extensions/<id>/` with an `index.ts` that default-exports
`defineExtension({ id, load: () => import('./Page') })`, plus the backend
package with the same id. The full walkthrough with a working example:
[docs/ARCHITECTURE.md → Adding an activity](../docs/ARCHITECTURE.md#adding-an-activity).
