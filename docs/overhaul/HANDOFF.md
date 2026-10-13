# Overhaul handoff (orchestrator state, 2026-10-13)

The orchestrator's working notes, so it can resume after a context compaction.
The host reads the final REPORT.md, not this file.

## Ground rules
- The host writes German, so answer in German.
- Never push. `main` (1d6b5eb) is the pre-overhaul baseline; leave it, the main
  checkout and port 8000 alone.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Host's scope cut (tokens are tight):**
  - no accessibility/axe;
  - no big QA agent and no screenshot rounds;
  - only the follow-ups that matter.

## Where things are
- The integration branch `overhaul` lives in the worktree `.worktrees/overhaul`.
  HEAD is 0ced886 and contains:
  - waves 1+2: BE-core, FE-foundation, BE-features, GP, AC, AD;
  - the security review and its fixes (`docs/overhaul/SECURITY_REVIEW.md`, with a
    Resolution section);
  - INT-A: Dockerfile multi-stage, Makefile, CI, README/ARCHITECTURE/DEPLOY, the
    frontend README.
- Contracts:
  - `docs/overhaul/PLAN.md`
  - `WAVE2.md`
  - `contracts/api.md`
  - `contracts/web-serving.md`
  - `design/DESIGN.md`
- Gates on 0ced886, all green:

  | Gate | Result |
  |---|---|
  | `make lint`, `make typecheck`, `make openapi-check` | pass |
  | backend tests | 502 passed, 1 skipped |
  | Vitest | 307 passed |
  | e2e Chromium (per INT-A) | 173 passed, 22 skipped |
  | e2e Firefox (per INT-A) | 181 passed, 14 skipped |
  | `make docker-smoke` (per INT-A) | pass |

## Still running
- **INT-B** (worktree `.worktrees/ov-int-b`, branch `ov/int-b`, agent id
  a1342023807130d37). Its scope was cut. It does:
  - WebKit via `run_webkit.sh`, and fixes what breaks there;
  - the rendered-DOM blocker scan on all screens;
  - follow-ups a (join texts for joined guests in the identify answer),
    e (no `/api/me/photos` 403 after a ban), d (Fotobox number before the first
    upload), b (HelpDisclosure without a heading), g (DESIGN.md §6, the redundant
    `keep_screenshot_dir`, browser-check.py);
  - hardening the flaky e2e tests.

  When it reports, merge `ov/int-b` into overhaul, then run
  `make openapi && git diff` to check the schema.

## Still to do after INT-B
1. Small leftovers (do them yourself, cheaply):
   - Start empty-state copy builds "der <Titel>" for any activity (`src/guest`);
   - CLI tools' file timestamps use UTC, the admin exports use `VB_TIMEZONE`;
   - optional: `PRAGMA wal_checkpoint(TRUNCATE)` on shutdown.
2. Delete `backend/tests/e2e_legacy/` (PLAN wave 4). Done: removed after the overhaul.
3. Final runs, once each:
   - `make check` (lint, typecheck, test, openapi-check);
   - `make e2e`, `make e2e-firefox`, `make e2e-webkit`;
   - `make docker-smoke`.
4. A lean QA pass by the orchestrator: walk through each of the host's
   requirements once, in a browser (playwright-cli) or via the API, against a
   local server on a free port (not 8000):
   - QR/token gate and 404 hint;
   - join without a "no" option;
   - pseudonym, Instagram name;
   - Beer Cam bottle/cup;
   - Fotobox filters;
   - "Deine Bilder";
   - admin live: hide only;
   - manage: delete, ban guest, device ban, auto-ban release;
   - "user xy" link → the guest's uploads;
   - per-guest upload pause;
   - pause new guests + switching off with restore or keep;
   - stop all;
   - exports;
   - Instagram board ZIP/Erledigt.
5. Write `docs/overhaul/REPORT.md` (German, compact): what was done, the new
   structure and stack, the design, features new vs old, test numbers, the
   security results, decisions, open points, how to start it. Commit it, then
   give a short German chat summary.

## Open points for the report
- **SEC-13:** remove the `minimumReleaseAgeExclude` block in
  `frontend/pnpm-workspace.yaml` after 2026-10-13 16:30 UTC (18:30 German time),
  then run `pnpm install --frozen-lockfile`.
- WebKit is not in CI (the Playwright image is 3.5 GB). The other browsers are.
- The screenshot `docs/overhaul/design/shots/wave2-gp/02-start-photos-phone.png`
  shows the host's party name and handle. Fine for a private repo.
- Coolify still needs repo access: the repo is private and Coolify only has the
  "Public GitHub" source. Offer the GitHub App or a deploy key; this was never
  answered.
- Dropped by the host's scope cut:
  - axe/a11y
  - the extension card slot
  - font preload
  - the `data-*` passthrough refactor
- The admin contact sheet uses React Aria grid-list semantics: while photos are
  selected, a click selects instead of opening.
- The login lock trades availability for protection. After 20 failures in
  15 minutes, every login is refused for 5 minutes. Already logged-in admins keep
  working, a restart clears the lock, and direct loopback is exempt.
