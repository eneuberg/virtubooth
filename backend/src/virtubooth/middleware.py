"""Pure ASGI middlewares (no BaseHTTPMiddleware: keeps SSE streaming intact).

GuardMiddleware, in order:
1. `?t=<token of a QR code>` on a page URL: valid → set the access cookie
   (and a visitor id, if the browser has none), count the scan for that code
   and redirect to the same URL without the token; invalid → the "scan the
   QR code" page. Wrong tokens are rate limited per IP; over the limit every
   token gets that page without being checked.
2. state-changing requests must carry a same-origin Origin/Referer (CSRF).
3. request bodies: uploads stream through (they enforce their own cap), every
   other body must declare a Content-Length of at most MAX_JSON_BODY.
4. request budget for /api/: per guest device when identified, else per IP;
   admin sessions are exempt.

SecurityHeadersMiddleware adds CSP & co. and a default Cache-Control
(`no-store` for /api/, `private, no-cache` for pages; routes may set their own,
e.g. `/assets/` immutable and `/media/` private).
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .api.deps import admin_from_cookie
from .core import errors
from .core.ratelimit import RateLimiter
from .core.security import (
    ACCESS_COOKIE,
    GUEST_COOKIE_MAX_AGE,
    SECURITY_HEADERS,
    UID_COOKIE,
    client_ip,
    origin_allowed,
    set_cookie,
)
from .runtime import Core

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_JSON_BODY = 64 * 1024
# bodies that stream with their own cap: activity uploads and the poster template
_STREAMED_PATH = re.compile(r"^(?:/api/x/[a-z][a-z0-9-]{1,30}/upload|/api/admin/poster/template)$")
# paths where ?t= is never interpreted as a party token
_NO_TOKEN_PREFIXES = ("/api/", "/admin", "/assets/", "/media/", "/healthz")


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
            # a thread: a valid entry writes the visitor row (services/presence.py)
            response = await run_in_threadpool(self._token_entry, request)
            await response(scope, receive, send)
            return

        if request.method in UNSAFE_METHODS and not origin_allowed(request, core.settings):
            await _error(errors.bad_origin(), scope, receive, send)
            return

        if request.method in UNSAFE_METHODS and not _STREAMED_PATH.match(path):
            # no Content-Length and no Transfer-Encoding means no body (HTTP/1.1);
            # a chunked body of unknown length is refused
            declared = request.headers.get("content-length", "0")
            if "transfer-encoding" in request.headers or not declared.isdigit():
                err = errors.ApiError(411, "length_required", "Ungültige Anfrage.")
                await _error(err, scope, receive, send)
                return
            if int(declared) > MAX_JSON_BODY:
                await _error(
                    errors.ApiError(413, "too_large", "Anfrage zu groß."), scope, receive, send
                )
                return

        if path.startswith("/api/"):
            limiter, key = self._api_budget(request, path)
            if limiter is not None and not limiter.hit(key):
                await _error(errors.rate_limited(limiter.retry_after(key)), scope, receive, send)
                return

        await self.app(scope, receive, send)

    def _api_budget(self, request: Request, path: str) -> tuple[RateLimiter | None, str]:
        core = self.core
        # the admin shares the venue WiFi IP with every guest; never throttle moderation
        if path.startswith("/api/admin/") and admin_from_cookie(request, core) is not None:
            return None, ""
        # identified guests get their own bucket, so one noisy device on the
        # venue WiFi can't use up the budget of everyone behind the same IP
        public_id = core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
        if public_id:
            return core.limits.api_guest, f"uid:{public_id}"
        return core.limits.api_ip, client_ip(request)

    def _token_entry(self, request: Request) -> Response:
        core = self.core
        codes = core.services.codes
        failures, ip = core.limits.token_fail_ip, client_ip(request)
        # guessing: over the limit nothing is checked, so the answer says nothing
        if not failures.available(ip):
            return core.web.gate()
        code = codes.entry(request.query_params.get("t", ""))
        if code is None:
            failures.hit(ip)
            return core.web.gate()
        rest = [(k, v) for k, v in request.query_params.multi_items() if k != "t"]
        # "//evil.example/" would be a protocol-relative URL: always one leading slash
        target = "/" + request.url.path.lstrip("/") + (f"?{urlencode(rest)}" if rest else "")
        # carries Set-Cookie: no cache may keep it
        response = RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store"})
        set_cookie(
            response,
            request,
            core.settings,
            ACCESS_COOKIE,
            codes.access_cookie(code),
            max_age=GUEST_COOKIE_MAX_AGE,
        )
        # the dashboard's "Gescannt" and the code's statistics: a random
        # visitor id, kept when it has one
        core.services.presence.enter(request, response, code_id=code.id)
        return response


async def _error(err: errors.ApiError, scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(err.body(), status_code=err.status, headers=err.headers)
    await response(scope, receive, send)


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
                if scope.get("scheme") == "https":
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
                api = path.startswith("/api/")
                if "cache-control" not in headers:
                    # API answers are personal; pages depend on the cookies and
                    # revalidate via ETag, never from a shared cache
                    headers["Cache-Control"] = "no-store" if api else "private, no-cache"
                elif api and headers.get("content-type", "").startswith("text/event-stream"):
                    # FastAPI's SSE response says no-cache; the admin stream is personal
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)
