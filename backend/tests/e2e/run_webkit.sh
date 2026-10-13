#!/usr/bin/env bash
# Run the browser tests in WebKit (Safari's engine) inside the official
# Playwright image, which ships WebKit's system libraries and a mock camera.
#   backend/tests/e2e/run_webkit.sh                 # all e2e tests
#   backend/tests/e2e/run_webkit.sh -k booth -x     # extra pytest args
# The image has no Node: build the frontend on the host first
# (`pnpm build` in frontend/), the tests serve frontend/dist.
# Optional environment:
#   VB_WEBKIT_CONTAINER=<name>  names the container (to find or stop it)
#   VB_SCREENSHOT_DIR=<dir>     screenshots land there (owned by you, not root)
#   VB_BLOCKLISTS=<dir>         full filter lists for the rendered-DOM blocker scans
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
IMAGE="mcr.microsoft.com/playwright/python:v1.63.0-noble"
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "run_webkit.sh: no frontend build at $ROOT/frontend/dist: run 'pnpm build' in frontend/ first" >&2
  exit 1
fi
EXTRA=()
if [ -n "${VB_WEBKIT_CONTAINER:-}" ]; then
  EXTRA+=(--name "$VB_WEBKIT_CONTAINER")
fi
if [ -n "${VB_SCREENSHOT_DIR:-}" ]; then
  mkdir -p "$VB_SCREENSHOT_DIR"
  EXTRA+=(-v "$(cd "$VB_SCREENSHOT_DIR" && pwd)":/shots -e VB_SCREENSHOT_DIR=/shots)
fi
if [ -n "${VB_BLOCKLISTS:-}" ]; then
  EXTRA+=(-v "$(cd "$VB_BLOCKLISTS" && pwd)":/blocklists:ro -e VB_BLOCKLISTS=/blocklists)
fi
exec docker run --rm --ipc=host "${EXTRA[@]}" -e HOST_IDS="$(id -u):$(id -g)" \
  -v "$ROOT":/src:ro "$IMAGE" bash -c '
  set -e
  mkdir -p /tmp/src
  tar -C /src --exclude=./.git --exclude=./.worktrees --exclude=./backend/.venv \
      --exclude=./backend/data --exclude=./frontend/node_modules -cf - . | tar -C /tmp/src -xf -
  cd /tmp/src/backend
  pip install -q --root-user-action=ignore --break-system-packages -e . pytest httpx2 playwright==1.63.0 >/dev/null
  status=0
  VB_E2E_BROWSER=webkit python -m pytest -m e2e -q -p no:cacheprovider "$@" || status=$?
  if [ -n "${VB_SCREENSHOT_DIR:-}" ]; then chown -R "$HOST_IDS" /shots; fi
  exit $status
' -- "$@"
