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
# a random id per browser that opened a valid QR link (the dashboard's "Gescannt")
VISITOR_COOKIE = "vb_vid"

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


def _origin(url: str) -> tuple[str, str] | None:
    """(scheme, netloc) of an http(s) URL, lowercased, default port dropped."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.netloc or "@" in parts.netloc:
        return None
    return scheme, _normalize_netloc(parts.netloc, scheme)


def _hostname(netloc: str) -> str:
    try:
        return urlsplit(f"//{netloc}").hostname or netloc
    except ValueError:
        return netloc


def _forwarded_https(request: Request) -> bool:
    """A proxy said the client came in over TLS (`X-Forwarded-Proto: https`),
    trusted or not. A browser page can't add that header to a cross-site
    request without a preflight, which fails: it only ever comes from a proxy
    or from a client acting on its own behalf."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    return "https" in {p.strip().lower() for p in forwarded.split(",")}


def origin_allowed(request: Request, settings: Settings) -> bool:
    """CSRF guard for state-changing requests.

    Browsers always send Origin on cross-site POST/PUT/PATCH/DELETE, and an
    attacker page cannot forge it. The full origin (scheme, host, port) of
    Origin (or Referer) must be one of:

    1. an entry of VB_ALLOWED_ORIGINS (exact);
    2. the origin of VB_PUBLIC_BASE_URL (exact);
    3. the request's own origin: its scheme (uvicorn applies a trusted
       X-Forwarded-Proto) with its Host header;
    4. `https://<Host>` for a plain-http request when TLS ends at a proxy the
       app doesn't trust for X-Forwarded-Proto: the proxy still says
       `X-Forwarded-Proto: https`, or VB_PUBLIC_BASE_URL is https, or
       VB_COOKIE_SECURE=true.

    An `http://` origin is refused (2. and 3. included) for a request that came
    in over TLS (own scheme or X-Forwarded-Proto https), and for the host of an
    https VB_PUBLIC_BASE_URL: anyone on the venue Wi-Fi can answer for
    `http://<that host>`. Only VB_ALLOWED_ORIGINS overrides that. Requests
    without Origin or Referer are refused.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or source == "null":
        return False
    origin = _origin(source)
    if origin is None:
        return False
    if origin in {_origin(o) for o in settings.allowed_origins}:
        return True
    scheme, netloc = origin
    own = request.url.scheme
    via_tls = own == "https" or _forwarded_https(request)
    public = _origin(settings.public_base_url) if settings.public_base_url else None
    if scheme == "http":
        if via_tls:
            return False
        if public and public[0] == "https" and _hostname(netloc) == _hostname(public[1]):
            return False
    if origin == public:
        return True
    host = request.headers.get("host", "")
    if not host:
        return False
    if scheme == own and netloc == _normalize_netloc(host, own):
        return True
    # TLS ends at a proxy whose X-Forwarded-Proto the app doesn't trust
    behind_tls = (
        via_tls or (public is not None and public[0] == "https") or settings.cookie_secure == "true"
    )
    return (
        scheme == "https"
        and own == "http"
        and behind_tls
        and netloc == _normalize_netloc(host, None)
    )
