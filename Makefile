# virtubooth developer tasks. `make` (or `make help`) lists them.
#
# Everything is overridable on the command line, e.g.
#   make dev PORT=8100              backend on :8100
#   make dev-web PORT=8100 WEB_PORT=5200
#   make e2e E2E_ARGS="-k beer -x"  extra pytest arguments
#   make e2e E2E_ARGS=tests/e2e/admin/test_live_e2e.py   one file (paths from backend/)
#   make e2e E2E_WORKERS=0          browser tests in one process (--pdb, breakpoints)
#   make docker IMAGE=virtubooth:test
# Needs uv, pnpm 11 with Node 22 (frontend/.node-version), and Docker for the
# docker/WebKit targets.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

# backend port (virtubooth serve), also the target of the Vite dev proxy
PORT ?= 8000
# Vite dev server port
WEB_PORT ?= 5173
# the settings `make dev` loads; created with fresh secrets (gen-env) when missing
ENV_FILE ?= .env
# VB_DATA_DIR for `make dev` unless ENV_FILE sets one (SQLite + photos). Relative
# VB_DATA_DIR / VB_WEB_DIR values in ENV_FILE count from the repository root.
DATA_DIR ?= $(CURDIR)/data
# image name for docker / docker-smoke
IMAGE ?= virtubooth:local
# docker-smoke publishes its throwaway container on 127.0.0.1:SMOKE_PORT
SMOKE_PORT ?= 8180
# setup with the Live-Wall analysis extra (mediapipe, onnxruntime, OpenCV): ML=1
ML ?=
# extra arguments for `make models`, e.g. --with-age (FairFace, 87 MB)
MODELS_ARGS ?=
# extra pytest arguments for test / the e2e targets
PYTEST_ARGS ?=
E2E_ARGS ?=
# parallel pytest workers (pytest-xdist; 0 = one process). Every e2e worker runs its
# own servers and browser: 0.8 (Chromium) to 1 GB (Firefox, WebKit) of RAM each
E2E_WORKERS ?= 4
WEBKIT_WORKERS ?= $(E2E_WORKERS)
TEST_WORKERS ?= 4
# e2e-changed runs the e2e tests changed since this ref
BASE ?= main

UV_BACKEND := uv run --project backend
# pytest arguments for N workers: nothing for 0
xdist = $(if $(filter-out 0,$(1)),-n $(1) --dist worksteal)

# What `pnpm build` reads: frontend/'s files without node_modules and dist (git knows
# which), and their folders (deleting a file changes its folder). The e2e targets
# rebuild frontend/dist only when one of them is newer; `make build-web` always builds.
WEB_INPUTS := $(shell git ls-files -co --exclude-standard -- frontend 2>/dev/null)
WEB_INPUTS := $(wildcard $(WEB_INPUTS)) $(patsubst %/,%,$(sort $(dir $(WEB_INPUTS))))
ifeq ($(strip $(WEB_INPUTS)),)
WEB_INPUTS := FORCE
endif

.PHONY: help setup browsers models dev dev-web build-web openapi openapi-check lint \
        typecheck test e2e e2e-firefox e2e-webkit e2e-changed docker docker-smoke \
        check check-all clean FORCE
# a failed build leaves no frontend/dist/index.html that looks up to date
.DELETE_ON_ERROR:
# check-all's steps one after the other even under -j (each e2e run is parallel itself)
.NOTPARALLEL: check-all

help: ## list the targets
	@echo "usage: make <target> [PORT=8000 WEB_PORT=5173 IMAGE=virtubooth:local ...]"
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{ printf "  %-14s %s\n", $$1, $$2 }'

setup: ## install the backend (uv sync; ML=1 adds the Live-Wall analysis extra) and frontend (pnpm install) dependencies
	cd backend && uv sync $(if $(filter 1,$(ML)),--extra ml)
	cd frontend && pnpm install --frozen-lockfile

browsers: ## download the Playwright browsers for e2e (Linux CI: add --with-deps)
	cd backend && uv run playwright install chromium firefox

$(ENV_FILE):
	cd backend && uv run virtubooth gen-env > $(abspath $(ENV_FILE))
	@echo "wrote $(ENV_FILE) with fresh secrets (VB_PARTY_TOKEN, VB_ADMIN_PASSWORD, ...)"

models: $(ENV_FILE) ## Live-Wall analysis: install the ml extra, download the models into <data>/wall/models
	cd backend && uv sync --extra ml
	@set -a && . $(abspath $(ENV_FILE)) && set +a && \
	  VB_DATA_DIR="$${VB_DATA_DIR:-$(DATA_DIR)}" && \
	  case "$$VB_DATA_DIR" in /*) ;; *) VB_DATA_DIR="$(CURDIR)/$$VB_DATA_DIR" ;; esac && \
	  cd backend && uv run python -m virtubooth.extensions.wall.enrich models fetch \
	    --data-dir "$$VB_DATA_DIR" $(MODELS_ARGS)

dev: $(ENV_FILE) ## backend on :PORT with reload; serves frontend/dist, or placeholders + API without a build
	@if [ -f frontend/dist/index.html ]; then \
	  echo "serving frontend/dist (rebuild: make build-web; live UI: make dev-web)"; \
	else \
	  echo "no frontend build: placeholder pages + API (VB_DEV=1); run make dev-web for the UI"; \
	fi
	@set -a && . $(abspath $(ENV_FILE)) && set +a && \
	  token="$$VB_PARTY_TOKEN" && \
	  echo "open http://localhost:$(PORT)/?t=$$token (admin: http://localhost:$(PORT)/admin)" && \
	  echo "  (VB_PARTY_TOKEN is QR code 1's token from the first start; after a token change in the admin, take the link from Admin -> QR-Codes)" && \
	  export VB_DATA_DIR="$${VB_DATA_DIR:-$(DATA_DIR)}" && \
	  case "$$VB_DATA_DIR" in /*) ;; *) VB_DATA_DIR="$(CURDIR)/$$VB_DATA_DIR" ;; esac && \
	  case "$${VB_WEB_DIR:-/}" in /*) ;; *) export VB_WEB_DIR="$(CURDIR)/$$VB_WEB_DIR" ;; esac && \
	  if [ ! -f frontend/dist/index.html ]; then export VB_DEV=1; fi && \
	  cd backend && exec uv run virtubooth serve --port $(PORT) --reload

dev-web: ## Vite dev server on :WEB_PORT (hot reload), proxying /api, /media and ?t= to :PORT
	@echo "needs the backend: make dev PORT=$(PORT) (in another terminal)"
	@echo "open http://localhost:$(WEB_PORT)/?t=<VB_PARTY_TOKEN>; the dev-only UI gallery: /__ui"
	cd frontend && VB_API_URL=http://127.0.0.1:$(PORT) exec pnpm dev --port $(WEB_PORT)

build-web: ## production frontend build into frontend/dist (+ .br/.gz, blocker name check)
	cd frontend && pnpm build

frontend/dist/index.html: $(WEB_INPUTS)
	cd frontend && pnpm build

FORCE:

openapi: ## export the OpenAPI schema to frontend/openapi.json and regenerate src/api/schema.gen.ts
	cd backend && uv run virtubooth export-openapi -o ../frontend/openapi.json
	cd frontend && pnpm gen:api

openapi-check: openapi ## fail when the committed schema or client types are out of date
	@git diff --exit-code -- frontend/openapi.json frontend/src/api/schema.gen.ts \
	  || { echo "openapi drift: commit the regenerated files (make openapi)"; exit 1; }

lint: ## ruff check + format check (all Python, Markdown snippets), oxlint + prettier
	$(UV_BACKEND) ruff check .
	$(UV_BACKEND) ruff format --check .
	cd frontend && pnpm lint

typecheck: ## mypy --strict (backend, scripts/smoke.py), tsc -b (frontend)
	cd backend && uv run mypy
	$(UV_BACKEND) mypy --strict --python-version 3.12 scripts/smoke.py
	cd frontend && pnpm typecheck

test: ## unit + API tests (pytest, TEST_WORKERS in parallel) and frontend unit tests (Vitest)
	cd backend && uv run pytest -q $(call xdist,$(TEST_WORKERS)) $(PYTEST_ARGS)
	cd frontend && pnpm test

e2e: frontend/dist/index.html ## browser tests in Chromium, E2E_WORKERS in parallel (rebuilds frontend/dist if needed)
	cd backend && uv run pytest -m e2e -q $(call xdist,$(E2E_WORKERS)) $(E2E_ARGS)

e2e-firefox: frontend/dist/index.html ## the browser tests in Firefox
	cd backend && VB_E2E_BROWSER=firefox uv run pytest -m e2e -q $(call xdist,$(E2E_WORKERS)) $(E2E_ARGS)

e2e-webkit: frontend/dist/index.html ## the browser tests in WebKit (Safari's engine), inside the Playwright Docker image
	backend/tests/e2e/run_webkit.sh $(call xdist,$(WEBKIT_WORKERS)) $(E2E_ARGS)

e2e-changed: frontend/dist/index.html ## Chromium e2e tests changed since BASE (committed or not); a changed helper runs them all
	@changed=$$( { git diff --name-only --diff-filter=d $(BASE)... -- backend/tests/e2e; \
	               git diff --name-only --diff-filter=d HEAD -- backend/tests/e2e; \
	               git ls-files -o --exclude-standard -- backend/tests/e2e; } | sort -u ); \
	  tests=$$(grep -E '/test_[^/]*\.py$$' <<<"$$changed" | sed 's|^backend/||' || true); \
	  if grep -qvE '/test_[^/]*\.py$$|^$$' <<<"$$changed"; then tests=tests/e2e; fi; \
	  if [ -z "$$tests" ]; then echo "e2e-changed: no e2e test changed since $(BASE)"; exit 0; fi; \
	  echo "e2e-changed:" $$tests; \
	  cd backend && uv run pytest -m e2e -q $(call xdist,$(E2E_WORKERS)) $$tests $(E2E_ARGS)

docker: ## build the container image (IMAGE); unchanged layers come from Docker's build cache
	docker build -t $(IMAGE) .

docker-smoke: docker ## run IMAGE on 127.0.0.1:SMOKE_PORT and check it end to end, then remove it
	VB_SMOKE_BUILD=0 VB_SMOKE_IMAGE=$(IMAGE) VB_SMOKE_PORT=$(SMOKE_PORT) scripts/docker-smoke.sh

check: openapi-check ## the everyday gate: OpenAPI drift, lint + typecheck + test side by side, Chromium e2e
	@$(MAKE) -j3 --output-sync=target lint typecheck test
	@$(MAKE) e2e
	@echo "check: all green"

check-all: check e2e-firefox e2e-webkit docker-smoke ## everything: check, then Firefox, WebKit and the Docker smoke test
	@echo "check-all: all green"

clean: ## remove build outputs and caches (never data/, .env or dependencies)
	rm -rf frontend/dist frontend/dist-gallery frontend/node_modules/.tmp frontend/node_modules/.vite
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache .mypy_cache .ruff_cache
	rm -rf backend/test-results test-results
	find backend scripts docs -name __pycache__ -type d -prune -exec rm -rf {} +
