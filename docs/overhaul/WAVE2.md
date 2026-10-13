# Wave 2: shared rules for GP, AC, AD

The orchestrator's brief for the three frontend agents of wave 2. PLAN.md stays
the contract; this file adds what wave 1 changed and how the three agents avoid
colliding.

## State after wave 1

- `backend/`: restructured FastAPI app (BE-core). `cd backend && uv run pytest -q`
  is green. Contracts: `docs/overhaul/contracts/api.md` and `web-serving.md`.
- `frontend/`: React 19 + Vite 8 + TS + Tailwind 4 + React Aria
  (FE-foundation). Read `docs/overhaul/design/DESIGN.md` first, then look at
  `docs/overhaul/design/shots/final/` (mockups) and `shots/gallery/` (real
  components). The dev gallery: `pnpm dev`, then `/__ui`.
- `frontend/src/api/types.ts` aliases the real schema. Export-job types are still
  hand-written in `types.pending.ts`, because BE-features builds those endpoints in
  parallel.
- `src/api/events.ts`: `openAdminEvents({onEvent, onStatus, since})`; events carry
  `id`; `stream.resync` exists.
- The e2e harness is `backend/tests/e2e/conftest.py`. It serves `frontend/dist`
  (build it first: `cd frontend && pnpm build`). Fixtures: `live`, `page`,
  `context`, `admin_page`, `new_context(browser, device)`, `track_errors`,
  `wait_until_ready`, `shot`, and **`join_via_api(page, live, instagram=None,
  fp_hash=None)`** for a joined guest without the UI.
- Run e2e from `backend/`:
  `uv run pytest tests/e2e/<dir> -m e2e -q`, with `VB_E2E_BROWSER=firefox` for
  Firefox. Screenshots go to `VB_SCREENSHOT_DIR=<dir>`.
- Legacy DOM tests to port are in `backend/tests/e2e_legacy/` (not collected).
  Map: `docs/overhaul/analysis/test-suite-map.md`.
- The old frontend is the behaviour reference. Read it with
  `git show main:virtubooth/static/<path>` (also `main:virtubooth/extensions/*/static/`).
  Behaviour inventory: `docs/overhaul/analysis/architecture.md` §2–§5.

## Ownership (wave 2)

| Area | GP (guest platform) | AC (activities) | AD (admin) |
|---|---|---|---|
| `src/sdk/session.ts`, `device.ts`, `feedback.ts`, `platform.ts`, `debug.ts`, `share.ts` | ✔ | read | – |
| `src/sdk/components/GuestPass.tsx`, `ActivityMenu.tsx`, `StatusSlot.tsx` | ✔ | read/use | – |
| `src/sdk/components/ActivityShell.tsx` | read | ✔ (ownership moved to AC: the camera frame is AC's) | – |
| `src/sdk/camera/*`, `upload.ts`, `outbox.ts`, `extension.ts` | read | ✔ | – |
| `src/extensions/**` | read | ✔ | – |
| `src/guest/**`, `index.html`, `gate.html`, `public/boot-check.js` | ✔ | – | – |
| `src/admin/**`, `admin.html` | – | – | ✔ |
| `src/ui/*` (existing files) | read-only | read-only | read-only |
| `src/api/*`, `src/lib/*`, `src/styles/app.css`, configs, `package.json` | read-only* | read-only* | read-only* |
| `backend/tests/e2e/guest/` | ✔ | – | – |
| `backend/tests/e2e/activities/` | – | ✔ | – |
| `backend/tests/e2e/admin/` | – | – | ✔ |
| `backend/tests/e2e/conftest.py` | only its `LEGACY` section (port the join helpers) | – | – |
| `backend/src/**` | – | – | – |

\* **Adding** a NEW file is fine anywhere in your own areas, and in `src/ui/`,
`src/lib/` or `src/styles/` when it is truly shared. Name it specifically
(`src/ui/PhotoLightbox.tsx`, not `src/ui/Modal2.tsx`) and mention it in your report.
If an existing shared file needs a change (a `src/ui` component bug, a missing token,
a new dependency, a backend fix), don't edit it. Work around it locally and list the
exact change in your report; the orchestrator applies it at merge. The one
exception: a one-line, obviously-correct fix that blocks you. Make it in its own
commit titled `shared: …`, so the orchestrator sees it.

Each e2e package (`guest/`, `activities/`, `admin/`) gets its own `__init__.py`
and, if needed, its own `conftest.py` for area fixtures. Import the shared ones with
`from ..conftest import …`.

## Rules

- Work only in your worktree. Never touch the main checkout, port 8000, or the
  other worktrees. Never push. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Never use a bare `git stash`.
- **RAM is tight**: three agents share about 3 GB, so:
  - run **one browser at a time**, and e2e serially (no xdist);
  - close playwright-cli sessions when done;
  - don't leave `vite dev` running. Prefer `pnpm build`, then e2e or
    `pnpm serve:dist`.
- Ports for manual servers: GP 8150–8159, AC 8160–8169, AD 8170–8179.
- **Skills:** read `~/.claude/skills/frontend-design/SKILL.md`,
  `web-design-guidelines/SKILL.md` (its rules are in
  `docs/overhaul/analysis/web-interface-guidelines.md`), `playwright-cli/SKILL.md`
  and `webapp-testing/SKILL.md`. Use `awesome-design` only for a reference.
- **Design:** the Kontaktbogen tokens and components. No new colours, sizes or
  radii outside the tokens. The UX audit §3.4 glossary is binding copy. Typography:
  German „…“, `…`, NBSP before units, tabular numbers. Lucide icons, no emoji in
  chrome.
- **CSP:** `script-src 'self'; style-src 'self'`. Nothing may inject `<style>` or
  use `eval`, and nothing may set a `style` *attribute* as markup
  (`setAttribute('style')`, `dangerouslySetInnerHTML`). React `style={{…}}` goes
  through the CSSOM and is allowed (DESIGN.md "CSP"); prefer classes and tokens.
  Every e2e test must end with zero console errors
  (`page.js_errors == []`).
- **Content blockers:** neutral names for files, classes, ids, test ids and
  storage keys. Avoid `ad`, `ads`, `banner`, `track`, `analytics`, `consent`,
  `cookie`, `popup`, `social`, `share-` and `sponsor` as words in any of them. The
  API paths stay as they are. `pnpm build` runs `check-names`.
- **Test ids:** keep today's where the concept still exists (join, tile-*, shutter,
  user-chip → guest-pass, the admin ids from analysis/admin-ui-inventory.md). New UI
  gets neutral ones.
- **Screenshots:** look at every one you take. Viewports: phone 390×844, small
  360×640, landscape 844×390, desktop 1440×900. Keep at most about 20 final PNGs
  under `docs/overhaul/design/shots/wave2-<gp|ac|ad>/`, each under 250 KB.
- **Done means** all of these pass:
  - `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`;
  - `uv run pytest -q` (backend);
  - your e2e package in Chromium **and** Firefox, with zero console errors.

  Commit in logical steps. Then reply with a report:
  - what you built
  - test counts per browser
  - what you ported from legacy, and what you dropped and why
  - shared-file changes you need
  - open issues
  - notes for the other agents / INT
