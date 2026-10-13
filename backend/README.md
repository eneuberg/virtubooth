# virtubooth backend

FastAPI + SQLite. It serves the JSON API, the photos, the admin event stream and
the built frontend (`frontend/dist`). The root [README](../README.md) describes
the product, [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) how the layers
work together, and the root `Makefile` wraps the commands below
(`make help`).

## Commands (run in `backend/`)

```sh
uv sync                                   # Python 3.14 venv in backend/.venv (dev tools included)
uv run pytest -q                          # unit + API tests (e2e are deselected)
uv run pytest -n 4 -q                     # the same, in parallel (pytest-xdist; -n auto = one per core)
uv run ruff check . && uv run ruff format --check .
uv run mypy src                           # strict, with the pydantic plugin
uv run virtubooth export-openapi -o ../frontend/openapi.json   # then `pnpm gen:api` in frontend/
uv run virtubooth gen-env > ../.env       # fresh secrets
set -a && . ../.env && set +a && uv run virtubooth serve        # :8000 (--port, --reload)
VB_DEV=1 uv run virtubooth serve          # without a frontend build: placeholder pages + the API
uv run playwright install chromium firefox                      # once, for e2e
uv run pytest -m e2e                      # browsers against frontend/dist (build it first)
VB_E2E_BROWSER=firefox uv run pytest -m e2e
tests/e2e/run_webkit.sh                   # WebKit in the Playwright Docker image
VB_BLOCKLISTS=.blocklists uv run pytest tests/unit/test_core_blockers.py   # full filter lists
uv run python -m virtubooth.tools.qr --help                     # also: timelapse, export
```

From the repository root, `uv run --project backend ruff check .` lints every
Python file in the repo (`ruff.toml` extends this project's settings), and
`scripts/docker-smoke.sh` checks the container image end to end.

Settings are `VB_*` environment variables (`../.env.example`,
[docs/DEPLOY.md](../docs/DEPLOY.md#settings)); the app never reads a `.env`
file itself. `VB_WEB_DIR` points at the built frontend (default:
`../frontend/dist` when it exists, `/app/web` in Docker). Without one the
server refuses to start, unless `VB_DEV=1`.

## Layout (`src/virtubooth/`)

| Path | What |
|---|---|
| `__main__.py` | CLI: `serve` (default), `gen-env`, `export-openapi` |
| `app.py` | `create_app(settings, extensions=None)`: the composition root |
| `settings.py` | pydantic-settings (`VB_*`), secrets as `SecretStr`, `ConfigError` |
| `runtime.py` | `Core`: settings, db, repos, services, bus, signer, limits, web, extensions |
| `middleware.py` | pure ASGI: token entry, CSRF origin check, body cap, API budget, security headers |
| `openapi.py` | the deterministic schema export (sorted keys, dummy settings, every built-in extension) |
| `core/` | errors (`ErrorCode`, `ErrorBody`, `ApiError`), security, events (bus, replay), ratelimit, logs, clock |
| `db/` | `Database` (one connection, nested transactions, on-commit hooks), `migrations.py` (append only) |
| `domain/` | dataclasses (`User`, `Photo`, ...), constants, pseudonyms, export job types |
| `repositories/` | one per aggregate (users, photos, bans, app_settings, admin_sessions, audit, exports, instagram) + admin read models; SQL only |
| `services/` | identity, uploads, moderation, upload controls, admin auth, admin views, typed events, export jobs (one worker thread, `export_runners.py`), Instagram board |
| `api/` | `deps.py` (Annotated dependencies), `schemas/` (pydantic In/Out, events), `routers/` (guest, uploads, media, health, `admin/*`) |
| `web/` | serving `VB_WEB_DIR`: HTML entries, gate/404, `/assets` |
| `extensions/` | `sdk.py` (Extension, UploadPolicy, discovery), `beer/`, `booth/` (filters.json) |
| `tools/` | qr, timelapse, export (`python -m virtubooth.tools.<x>`); the admin's export jobs reuse their functions |

Rules of thumb:

- Routers are thin: parse, call one service, build the response model.
- Services own the transaction: the change, its audit entry and its events
  commit together (`with db.tx():`, events via `db.on_commit`). Files are
  deleted after the commit.
- Repositories only run SQL; they nest inside the service's transaction.
- Every route declares a response model; errors are `ErrorBody`
  (`{error: ErrorCode, message}`) declared with `error_responses(...)`.
- A new error code goes into `core/errors.py` `ErrorCode`; a new event into
  `api/schemas/events.py` (payload, event model, `AdminEvent` union) and
  `services/events.py`.
- Schema changes: append a step to `db/migrations.py` `MIGRATIONS`.
- Any change to a route or schema: `make openapi` (from the root) and commit
  `frontend/openapi.json` + `frontend/src/api/schema.gen.ts`; CI diffs them.
- A new activity: see [Adding an activity](../docs/ARCHITECTURE.md#adding-an-activity).

## Tests (`tests/`)

| Path | What |
|---|---|
| `conftest.py` | settings (no `VB_*` from the shell), app, clients, `guest()`, `admin`, stub web dir |
| `api/` | the HTTP API and pages through `TestClient` (SSE through a live uvicorn) |
| `unit/` | migrations, tools, settings, events, OpenAPI export, content blockers, frontend contract |
| `fixtures/` | `blocker_rules.txt`, `web/` (a stub frontend build) |
| `e2e/` | Playwright harness serving `frontend/dist` (skipped without a build): `guest/`, `activities/`, `admin/`, `run_webkit.sh` |

Contracts for the frontend: `../docs/overhaul/contracts/web-serving.md` and
`../docs/overhaul/contracts/api.md`.
