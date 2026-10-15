# virtubooth container image.
#
#   docker build -t virtubooth:local .
#   docker compose up -d --build        (see compose.yaml and docs/DEPLOY.md)
#
# Three stages:
#   web      Node: builds the React frontend (frontend/) into frontend/dist
#   build    Python: resolves the locked backend dependencies with uv into /opt/venv
#   runtime  python slim + ffmpeg (timelapse exports) + /opt/venv + the built
#            frontend in /app/web (VB_WEB_DIR). Nothing else: no Node, no uv,
#            no sources, no tests.
# The app runs as an unprivileged user (uid/gid 10001) and keeps all state in
# the /data volume.
#
# Live-Wall photo analysis (optional; sizes: docs/DEPLOY.md "Live-Wall"):
#   docker build --build-arg VB_ML=1 -t virtubooth:ml .
#       adds the `ml` extra (mediapipe, onnxruntime, OpenCV) + libEGL/GLES;
#       the models then go to /data/wall/models (the data volume, so they
#       survive rebuilds): the admin's „Modelle herunterladen“ button in
#       ML-Pipeline, or `virtubooth wall models fetch` in the container
#   docker build --build-arg VB_ML=1 --build-arg VB_BAKE_MODELS=1 -t virtubooth:ml .
#       also downloads the models (SHA256-checked) into /opt/vb-models
# Without VB_ML the image is unchanged and only the basic analysis (Pillow) runs.
# docker-compose.coolify.yaml builds with VB_ML=1 (Coolify variables VB_ML and
# VB_BAKE_MODELS); compose.yaml and a plain `docker build` use the defaults below.

# Keep these in sync with the repo files they mirror:
#   frontend/.node-version, frontend/package.json "packageManager",
#   backend/.python-version, and the uv version CI uses (.github/workflows/ci.yml).
ARG NODE_IMAGE=node:22.22.1-trixie-slim
ARG PNPM_VERSION=11.28.5
ARG PYTHON_IMAGE=python:3.14.8-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.18
# 1 = with the `ml` extra (Live-Wall photo analysis); 1 = bake the models in too
ARG VB_ML=0
ARG VB_BAKE_MODELS=0

FROM ${UV_IMAGE} AS uv

# ------------------------------------------------------------------ web stage
FROM ${NODE_IMAGE} AS web
ARG PNPM_VERSION

# corepack (0.24 in this image) cannot run pnpm 11, so install it with npm.
# CI=true: pnpm never prompts.
RUN npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"
ENV CI=true

WORKDIR /web

# 1) Dependencies only: reused until the lockfile, the workspace settings or the
#    patches change. patches/ must be there before the install: the react-aria
#    patch removes two runtime <style> injections the strict CSP would block.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/patches ./patches
RUN --mount=type=cache,id=vb-pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store

# 2) The sources (.dockerignore keeps out tests, the UI gallery and local builds),
#    then the production build: vite build, precompressed .br/.gz siblings, and
#    the content-blocker name check (scripts/check-names.mjs).
COPY frontend/ ./
RUN pnpm build

# ---------------------------------------------------------------- build stage
FROM ${PYTHON_IMAGE} AS build
ARG VB_ML

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

# 1) Third-party dependencies only. This layer is reused until uv.lock or
#    pyproject.toml change, so code edits rebuild in seconds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project $([ "$VB_ML" = 1 ] && echo --extra ml)

# 2) The app itself, installed as a regular (non-editable) package, so the
#    runtime stage needs only /opt/venv. README.md is the package's readme.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable $([ "$VB_ML" = 1 ] && echo --extra ml)

# ------------------------------------------------- Live-Wall models (optional)
# VB_BAKE_MODELS=1: download the analysis models into /opt/vb-models (versioned
# URLs, SHA256-checked by the app's own downloader). 0: an empty folder.
FROM build AS models-1
RUN /opt/venv/bin/virtubooth wall models fetch --dest /opt/vb-models

FROM ${PYTHON_IMAGE} AS models-0
RUN mkdir -p /opt/vb-models

FROM models-${VB_BAKE_MODELS} AS models

# -------------------------------------------------------------- runtime stage
# runtime-0 is the default image; runtime-1 (VB_ML=1) adds what MediaPipe
# loads (libEGL, libGLESv2), MPLBACKEND=Agg and the baked models, if any.
FROM ${PYTHON_IMAGE} AS runtime-0

# ffmpeg: the timelapse export (admin "Export" section and
# `python -m virtubooth.tools.timelapse`)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

FROM ${PYTHON_IMAGE} AS runtime-1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*
ENV MPLBACKEND=Agg
COPY --from=models /opt/vb-models /opt/vb-models

FROM runtime-${VB_ML} AS runtime

# Fixed ids so a bind-mounted data directory can be chowned to 10001:10001.
# /data is created owned by that user: a fresh named volume inherits it.
RUN groupadd --gid 10001 virtubooth \
    && useradd --uid 10001 --gid virtubooth --no-log-init \
        --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin virtubooth \
    && install -d -o virtubooth -g virtubooth -m 0750 /data

COPY --from=build /opt/venv /opt/venv
# The built frontend, read-only for the app (owned by root).
COPY --from=web /web/dist /app/web

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VB_DATA_DIR=/data \
    VB_HOST=0.0.0.0 \
    VB_PORT=8000 \
    VB_WEB_DIR=/app/web \
    XDG_CACHE_HOME=/tmp/.cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    ORT_DISABLE_TELEMETRY=1
# The root filesystem may be read-only (docker-compose.coolify.yaml) and HOME
# (/nonexistent) does not exist: the ML libraries' caches (fontconfig,
# matplotlib's font list, a few hundred KB) go to the /tmp tmpfs instead.
# ORT_DISABLE_TELEMETRY: onnxruntime >= 1.31 would otherwise keep a device id
# and send usage events to Microsoft.

WORKDIR /app
USER 10001:10001

EXPOSE 8000
VOLUME /data

# urllib instead of curl: nothing extra to install. Non-2xx raises → unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('VB_PORT', '8000'), timeout=4)"]

# One process, one uvicorn worker, on purpose: rate limits and the event bus
# live in process memory. Never scale this to several workers or replicas.
CMD ["virtubooth", "serve"]
