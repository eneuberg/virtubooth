#!/usr/bin/env bash
# Run the browser tests in WebKit (Safari's engine) inside the official
# Playwright image, which ships WebKit's system libraries and a mock camera.
#   tests/e2e/run_webkit.sh                 # all e2e tests
#   tests/e2e/run_webkit.sh -k booth -x     # extra pytest args
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="mcr.microsoft.com/playwright/python:v1.63.0-noble"
exec docker run --rm --ipc=host -v "$ROOT":/src:ro "$IMAGE" bash -c '
  set -e
  mkdir -p /tmp/src
  tar -C /src --exclude=./.venv --exclude=./.worktrees --exclude=./data --exclude=./.git -cf - . | tar -C /tmp/src -xf -
  cd /tmp/src
  pip install -q --root-user-action=ignore --break-system-packages -e . pytest httpx2 playwright==1.63.0 >/dev/null
  VB_E2E_BROWSER=webkit python -m pytest -m e2e -q -p no:cacheprovider "$@"
' -- "$@"
