"""Application factory: the composition root."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.routers import guest, health, media, uploads
from .api.routers.admin import auth as admin_auth
from .api.routers.admin import poster as admin_poster
from .api.routers.admin import router as admin_router
from .core import errors
from .core.logs import install_access_log_filter
from .extensions.sdk import Extension, discover_extensions, validate_extension
from .middleware import GuardMiddleware, SecurityHeadersMiddleware
from .runtime import Core
from .settings import Settings, admin_password_warnings
from .web import routes as web_routes
from .web.frontend import WebFrontend


def create_app(settings: Settings, *, extensions: Sequence[Extension] | None = None) -> FastAPI:
    """The app for `settings`. `extensions`: None = the ones VB_EXTENSIONS names
    (default: every built-in one)."""
    exts = list(extensions) if extensions is not None else discover_extensions(settings.extensions)
    for ext in exts:
        validate_extension(ext)
    web = WebFrontend.from_settings(settings)
    core = Core.create(settings, exts, web)
    # export jobs a stopped server left queued or running have failed
    core.services.exports.recover()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        core.bus.bind_loop(asyncio.get_running_loop())
        # after uvicorn configured logging, so the filter isn't replaced
        install_access_log_filter()
        core.services.exports.attach()
        try:
            yield
        finally:
            await to_thread.run_sync(core.services.exports.detach)
            # empty the WAL: a copied data folder then holds everything in virtubooth.db
            await to_thread.run_sync(core.db.checkpoint)

    # runtime docs stay off; `virtubooth export-openapi` writes the schema
    app = FastAPI(
        title="virtubooth",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.core = core

    @app.exception_handler(errors.ApiError)
    async def _api_error(_request: Request, exc: errors.ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(errors.invalid_request().body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/") or exc.status_code != 404:
            return JSONResponse(
                {"error": f"http_{exc.status_code}", "message": str(exc.detail)},
                status_code=exc.status_code,
                headers=exc.headers,
            )
        return web_routes.not_found_page(request, core)

    app.include_router(health.router)
    app.include_router(guest.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_router)
    app.include_router(admin_poster.router)
    app.include_router(uploads.build_router(exts))
    app.include_router(media.router)
    for ext in exts:
        if ext.router is not None:
            app.include_router(
                ext.router,
                prefix=f"/api/x/{ext.id}",
                tags=[f"extension:{ext.id}"],
                responses=errors.error_responses(404, 422, 429),
            )
    app.include_router(web_routes.router)

    # last added = outermost
    app.add_middleware(GuardMiddleware, core=core)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def create_app_from_env() -> FastAPI:
    settings = Settings.from_env()
    log = logging.getLogger("virtubooth")
    if settings.cookie_secure == "false" and settings.public_base_url.startswith("https://"):
        log.warning(
            "VB_COOKIE_SECURE=false while VB_PUBLIC_BASE_URL is https: cookies may leak over http"
        )
    for warning in admin_password_warnings(settings.admin_password.get_secret_value()):
        log.warning(warning)
    return create_app(settings)
