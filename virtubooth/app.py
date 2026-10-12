"""Application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import admin_auth, identity, media, uploads
from .admin.api import router as admin_router
from .config import Settings
from .context import Core, Limits
from .db import Database
from .errors import ApiError
from .events import EventBus
from .extension import Extension, discover_extensions, validate_extension
from .middleware import GuardMiddleware, SecurityHeadersMiddleware
from .deps import has_access
from .pages import STATIC_DIR, gate_page, not_found_page
from .pages import router as pages_router
from .repo import Repo
from .security import Signer


def create_app(settings: Settings, *, extensions: Sequence[Extension] | None = None) -> FastAPI:
    exts = list(extensions) if extensions is not None else discover_extensions(settings.extensions)
    for ext in exts:
        validate_extension(ext)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.data_dir / "virtubooth.db")
    core = Core(
        settings=settings,
        db=db,
        repo=Repo(db, settings.data_dir),
        bus=EventBus(),
        signer=Signer(settings.secret_key),
        limits=Limits.from_settings(settings),
        extensions={e.id: e for e in exts},
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        core.bus.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(
        title="virtubooth", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.core = core

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"error": "invalid_request", "message": "Ungültige Anfrage."}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/") or exc.status_code != 404:
            return JSONResponse(
                {"error": f"http_{exc.status_code}", "message": str(exc.detail)},
                status_code=exc.status_code,
            )
        # without a QR scan, every unknown page says "scan the QR code" too
        return not_found_page() if has_access(request, core) else gate_page()

    app.include_router(identity.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_router)
    app.include_router(uploads.router)
    app.include_router(media.router)
    for ext in exts:
        if ext.router is not None:
            app.include_router(ext.router, prefix=f"/api/x/{ext.id}")
    app.include_router(pages_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # last added = outermost
    app.add_middleware(GuardMiddleware, core=core)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def create_app_from_env() -> FastAPI:
    return create_app(Settings.from_env())
