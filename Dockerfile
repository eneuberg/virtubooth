# virtubooth container image.
#
#   docker build -t virtubooth:local .
#   docker compose up -d --build        (see compose.yaml / README.md)
#
# Two stages: `build` resolves the locked dependencies with uv into /opt/venv,
# `runtime` is a plain python slim image with ffmpeg (for the timelapse tool),
# that venv and nothing else. The app runs as an unprivileged user (uid/gid
# 10001) and keeps all state in the /data volume.

# Keep the Python version in sync with .python-version.
ARG PYTHON_IMAGE=python:3.14.8-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.18

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- build stage
FROM ${PYTHON_IMAGE} AS build

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
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# 2) The app itself, installed as a regular (non-editable) package, so the
#    runtime stage needs only /opt/venv. README.md is the package's readme.
COPY pyproject.toml uv.lock README.md ./
COPY virtubooth ./virtubooth
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# -------------------------------------------------------------- runtime stage
FROM ${PYTHON_IMAGE} AS runtime

# ffmpeg is used by `python -m virtubooth.tools.timelapse`
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fixed ids so a bind-mounted data directory can be chowned to 10001:10001.
# /data is created owned by that user: a fresh named volume inherits it.
RUN groupadd --gid 10001 virtubooth \
    && useradd --uid 10001 --gid virtubooth --no-log-init \
        --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin virtubooth \
    && install -d -o virtubooth -g virtubooth -m 0750 /data

COPY --from=build /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VB_DATA_DIR=/data \
    VB_HOST=0.0.0.0 \
    VB_PORT=8000

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
