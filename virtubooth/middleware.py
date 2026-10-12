"""Pure ASGI middlewares (no BaseHTTPMiddleware: keeps SSE streaming intact).

GuardMiddleware, in order:
1. `?t=<party token>` on a page URL: valid → set the access cookie and redirect
   to the same URL without the token; invalid → the "scan the QR code" page.
2. state-changing requests must carry a same-origin Origin/Referer (CSRF).
3. per-IP request budget for /api/.

SecurityHeadersMiddleware adds CSP & co. and a default Cache-Control.
"""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import errors
from .context import Core
from .deps import admin_from_cookie
from .pages import gate_page
from .security import (
    ACCESS_COOKIE,
    GUEST_COOKIE_MAX_AGE,
    SECURITY_HEADERS,
    access_cookie_value,
    client_ip,
    constant_time_equals,
    origin_allowed,
    set_cookie,
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# paths where ?t= is never interpreted as a party token
_NO_TOKEN_PREFIXES = ("/api/", "/admin", "/static/", "/media/", "/healthz")


class GuardMiddleware:
    def __init__(self, app: ASGIApp, core: Core) -> None:
        self.app = app
        self.core = core

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path = request.url.path
        core = self.core

        if (
            request.method == "GET"
            and "t" in request.query_params
            and not path.startswith(_NO_TOKEN_PREFIXES)
        ):
            await self._token_entry(request)(scope, receive, send)
            return

        if request.method in UNSAFE_METHODS and not origin_allowed(request, core.settings):
            err = errors.ApiError(403, "bad_origin", "Anfrage von fremder Seite abgelehnt.")
            await JSONResponse(err.body(), status_code=403)(scope, receive, send)
            return

        # the admin shares the venue WiFi IP with every guest; never throttle moderation
        if path.startswith("/api/") and not (
            path.startswith("/api/admin/") and admin_from_cookie(request, core) is not None
        ):
            ip = client_ip(request)
            if not core.limits.api_ip.hit(ip):
                err = errors.rate_limited(core.limits.api_ip.retry_after(ip))
                response = JSONResponse(err.body(), status_code=err.status, headers=err.headers)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    def _token_entry(self, request: Request):  # type: ignore[no-untyped-def]
        core = self.core
        token = request.query_params.get("t", "")
        if not constant_time_equals(token, core.settings.party_token):
            return gate_page()
        rest = [(k, v) for k, v in request.query_params.multi_items() if k != "t"]
        target = request.url.path + (f"?{urlencode(rest)}" if rest else "")
        response = RedirectResponse(target, status_code=303)
        set_cookie(
            response,
            request,
            core.settings,
            ACCESS_COOKIE,
            access_cookie_value(core.settings, core.signer),
            max_age=GUEST_COOKIE_MAX_AGE,
        )
        return response


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if "cache-control" not in headers:
                    # API answers are personal; static files revalidate via ETag
                    headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_headers)
