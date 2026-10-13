"""Secrets, signed values, cookies, the CSRF origin check and response headers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response

from ..settings import Settings

ACCESS_COOKIE = "vb_access"
UID_COOKIE = "vb_uid"
ADMIN_COOKIE = "vb_admin"

GUEST_COOKIE_MAX_AGE = 30 * 24 * 3600

CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' blob: data:",
        "media-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    # QR links carry the party token: never leak it in a Referer
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def constant_time_equals(a: str, b: str) -> bool:
    # hash first so neither the content nor the length leaks through timing
    return hmac.compare_digest(
        hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest()
    )


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Signer:
    def __init__(self, key: str) -> None:
        self._key = key.encode()

    def mac(self, purpose: str, value: str) -> str:
        return _b64(hmac.new(self._key, f"{purpose}|{value}".encode(), hashlib.sha256).digest())

    def sign(self, purpose: str, value: str) -> str:
        return f"{value}.{self.mac(purpose, value)}"

    def unsign(self, purpose: str, signed: str | None) -> str | None:
        if not signed or "." not in signed or len(signed) > 256:
            return None
        value, _, mac = signed.rpartition(".")
        return value if hmac.compare_digest(mac, self.mac(purpose, value)) else None


def party_token_matches(settings: Settings, token: str) -> bool:
    return constant_time_equals(token, settings.party_token.get_secret_value())


def access_cookie_value(settings: Settings, signer: Signer) -> str:
    # derived from the party token itself: rotating the token logs everyone out
    return signer.mac("access", settings.party_token.get_secret_value())


def admin_password_tag(settings: Settings, signer: Signer) -> str:
    # stored with each admin session: changing the password ends all sessions
    return signer.mac("admin-pw", settings.admin_password.get_secret_value())[:22]


def cookie_secure(settings: Settings, request: Request) -> bool:
    if settings.cookie_secure == "auto":
        # an https public URL means guests always come in over TLS, even when the
        # proxy's X-Forwarded-Proto isn't trusted and the app only sees http
        return request.url.scheme == "https" or settings.public_base_url.startswith("https://")
    return settings.cookie_secure == "true"


def set_cookie(
    response: Response,
    request: Request,
    settings: Settings,
    name: str,
    value: str,
    *,
    max_age: int | None,
    samesite: Literal["lax", "strict"] = "lax",
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=cookie_secure(settings, request),
        samesite=samesite,
    )


def client_ip(request: Request) -> str:
    # uvicorn rewrites request.client from X-Forwarded-For only for proxies
    # listed in --forwarded-allow-ips, so this is safe to trust
    return request.client.host if request.client else "unknown"


def is_direct_loopback(request: Request) -> bool:
    """The request came straight from this machine: a loopback client address
    and no proxy header. A forwarded request never counts, so neither a proxy
    on this host nor a client that claims `X-Forwarded-For: 127.0.0.1` is
    treated as local."""
    if "x-forwarded-for" in request.headers or "forwarded" in request.headers:
        return False
    try:
        return ipaddress.ip_address(client_ip(request)).is_loopback
    except ValueError:
        return False


_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _normalize_netloc(netloc: str, scheme: str | None) -> str:
    """Lowercase and drop a default port. Without a scheme (the Host header)
    both 80 and 443 count as default: behind a TLS proxy the app may only ever
    see plain http."""
    netloc = netloc.lower()
    host, sep, port = netloc.rpartition(":")
    if sep and port.isdigit():
        if scheme in _DEFAULT_PORTS:
            defaults = {_DEFAULT_PORTS[scheme]}
        else:
            defaults = set(_DEFAULT_PORTS.values())
        if port in defaults:
            return host
    return netloc


def origin_allowed(request: Request, settings: Settings) -> bool:
    """CSRF guard for state-changing requests.

    Browsers always send Origin on cross-site POST/PUT/PATCH/DELETE, and an
    attacker page cannot forge it, so matching it against our own Host header is
    enough. Requests without Origin or Referer are rejected.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or source == "null":
        return False
    parts = urlsplit(source)
    if not parts.scheme or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    if origin in (o.lower().rstrip("/") for o in settings.allowed_origins):
        return True
    host = request.headers.get("host", "")
    return _normalize_netloc(parts.netloc, parts.scheme) == _normalize_netloc(host, None)
