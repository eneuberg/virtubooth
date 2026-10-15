"""Allgemeines: the event name and the public address the host sets in the admin.

The name lives in the `settings` table (`event`) and overrides VB_PARTY_NAME
everywhere a guest or an export sees it; deleting it (reset) brings the env
value back. Admin screens follow through the `settings.event` event; guests
have no event stream and pick it up when they next fetch `/api/extensions`
(the guest app polls it every minute while visible).

The public address (`public_address`) overrides VB_PUBLIC_BASE_URL for the QR
codes, posters and the Live-Wall's code; with neither, they use the origin the
admin is open on. It is never used for cookie or CSRF decisions (env only). The
check fetches `<address>/healthz?probe=<nonce>` (no redirects, 4 s, at most
4 KB) and expects `probe_mac(nonce)`: so "ok" means it reaches THIS server.
A failed check is a warning, never a block (hairpin NAT: the server may not
reach its own public address).

The admin password lives in AdminAuthService (it shares the login's limits).
"""

from __future__ import annotations

import http.client
import json
import re
import secrets
import socket
import ssl
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from ..api.schemas.host_settings import (
    AddressCheck,
    AdminSettingsOut,
    EventSettings,
    PasswordState,
    PublicAddress,
)
from ..core import errors
from ..core.clock import now_iso
from ..core.security import Signer
from ..db.database import Database
from ..repositories.app_settings import EVENT_KEY, PUBLIC_ADDRESS_KEY, StoredCheck
from ..repositories.container import Repositories
from ..settings import Settings
from .events import AdminEvents

if TYPE_CHECKING:
    from ..runtime import Core

EVENT_NAME_MAX = 60
_WHITESPACE = re.compile(r"\s+")
# bidi embeddings, overrides and isolates: they could turn the rest of a page around
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")


def invalid_event_name() -> errors.ApiError:
    return errors.bad_request("Der Name braucht 1 bis 60 Zeichen.", "invalid_event_name")


def normalize_event_name(raw: str | None) -> str | None:
    """The name to store, or None for "back to VB_PARTY_NAME" (null or blank).

    Strips, collapses every run of whitespace (line breaks included) to one
    space, then refuses control characters and names nobody can see (only
    invisible format characters such as zero-width spaces): 400
    `invalid_event_name`, like a name over 60 characters."""
    if raw is None:
        return None
    name = _WHITESPACE.sub(" ", raw).strip()
    if not name:
        return None
    for ch in name:
        if unicodedata.category(ch) in ("Cc", "Cs") or ch in _BIDI_CONTROLS:
            raise invalid_event_name()
    # spaces and format characters (Cf) alone show nothing; an emoji newer than
    # this Python's Unicode tables (Cn) still counts as visible
    visible = any(
        not unicodedata.category(ch).startswith("Z") and unicodedata.category(ch) != "Cf"
        for ch in name
    )
    if not visible or len(name) > EVENT_NAME_MAX:
        raise invalid_event_name()
    return name


# ------------------------------------------------------------ public address

AddressSource = Literal["setting", "env", "auto"]
PUBLIC_ADDRESS_MAX = 300
PROBE_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
PROBE_TIMEOUT = 4.0
PROBE_MAX_BYTES = 4096
PROBE_MAC_LENGTH = 16


def invalid_public_address() -> errors.ApiError:
    return errors.bad_request(
        "Die Adresse muss mit http:// oder https:// beginnen und darf kein ?, kein # und "
        "keinen Benutzernamen enthalten, z. B. https://party.example.com.",
        "invalid_public_address",
    )


def normalize_public_address(raw: str | None) -> str | None:
    """The address to store (like `tools/qr.normalize_base_url`: trimmed, no
    trailing slash, scheme and host lower case), or None for blank. 400
    `invalid_public_address` for anything else than http(s)://host[:port][/path]."""
    if raw is None:
        return None
    url = raw.strip().rstrip("/")
    if not url:
        return None
    if len(url) > PUBLIC_ADDRESS_MAX or any(c.isspace() or ord(c) < 32 for c in url):
        raise invalid_public_address()
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise invalid_public_address() from None
    if (
        parts.scheme.lower() not in ("http", "https")
        or not parts.hostname
        or parts.query
        or parts.fragment
        or "?" in url
        or "#" in url
        or parts.username is not None
        or parts.password is not None
    ):
        raise invalid_public_address()
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return f"{parts.scheme.lower()}://{netloc}{parts.path}"


def probe_mac(signer: Signer, nonce: str) -> str:
    """What `/healthz?probe=<nonce>` answers: only this server's key makes it."""
    return signer.mac("probe", nonce)[:PROBE_MAC_LENGTH]


@dataclass(frozen=True)
class ProbeAnswer:
    """What the address answered: HTTP status, the first bytes, a redirect target."""

    status: int
    body: bytes
    location: str | None = None


class ProbeError(Exception):
    """No answer at all; `message` is German for the admin."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


ProbeFetcher = Callable[[str], ProbeAnswer]


def fetch_probe(url: str) -> ProbeAnswer:
    """GET `url`: no redirects followed, PROBE_TIMEOUT per step, at most
    PROBE_MAX_BYTES read, http and https only (system CA store)."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"
    conn: http.client.HTTPConnection
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(
            parts.hostname or "", parts.port, timeout=PROBE_TIMEOUT,
            context=ssl.create_default_context(),
        )  # fmt: skip
    elif parts.scheme == "http":
        conn = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=PROBE_TIMEOUT)
    else:
        raise ProbeError("Nur http:// und https:// gehen.")
    try:
        conn.request(
            "GET", path, headers={"Accept": "application/json", "User-Agent": "virtubooth"}
        )
        res = conn.getresponse()
        body = res.read(PROBE_MAX_BYTES)
        return ProbeAnswer(status=res.status, body=body, location=res.getheader("Location"))
    except TimeoutError:
        raise ProbeError(f"Keine Antwort nach {PROBE_TIMEOUT:.0f} Sekunden.") from None
    except ssl.SSLError:
        raise ProbeError("Das HTTPS-Zertifikat passt nicht oder ist ungültig.") from None
    except ConnectionRefusedError:
        raise ProbeError("Verbindung abgelehnt.") from None
    except socket.gaierror:
        raise ProbeError("Den Namen findet das DNS nicht.") from None
    except OSError:
        raise ProbeError("Keine Verbindung.") from None
    except (http.client.HTTPException, ValueError):
        raise ProbeError("Die Antwort war kein gültiges HTTP.") from None
    finally:
        conn.close()


def event_name(settings: Settings, repos: Repositories) -> str:
    """The event name in use: the host's, else VB_PARTY_NAME. For code without
    the services (the export runners)."""
    stored = repos.app_settings.event_name()
    return stored.name if stored is not None else settings.party_name


class HostSettingsService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events
        # tests swap it for a fake (the real one opens a connection)
        self.fetch_probe: ProbeFetcher = fetch_probe

    def event_name(self) -> str:
        return event_name(self.core.settings, self.repos)

    def event(self) -> EventSettings:
        stored = self.repos.app_settings.event_name()
        default = self.core.settings.party_name
        return EventSettings(
            name=stored.name if stored else default,
            default_name=default,
            custom=stored is not None,
            updated_at=stored.at if stored else None,
            by=stored.by if stored else None,
        )

    def set_event_name(self, raw: str | None, *, actor: str) -> tuple[EventSettings, bool]:
        """Set the name (None or blank: back to VB_PARTY_NAME). Returns the new
        state and whether anything changed."""
        name = normalize_event_name(raw)
        with self.db.tx():
            stored = self.repos.app_settings.event_name()
            if (stored.name if stored else None) == name:
                return self.event(), False
            previous = self.event_name()
            at = now_iso()
            if name is None:
                self.repos.app_settings.delete(EVENT_KEY)
            else:
                self.repos.app_settings.put_event_name(name, by=actor, at=at)
            state = self.event()
            self.repos.audit.log(
                actor,
                "settings.event",
                details={"event_name": state.name, "previous": previous},
                at=at,
            )
            self.events.settings_event(state)
        return state, True

    def password(self) -> PasswordState:
        stored = self.repos.app_settings.admin_password()
        if stored is None:
            return PasswordState(source="env", changed_at=None)
        return PasswordState(source="admin", changed_at=stored.changed_at)

    def admin_settings(self, origin: str | None = None) -> AdminSettingsOut:
        return AdminSettingsOut(
            event=self.event(),
            password=self.password(),
            public_address=self.public_address(origin),
        )

    # ------------------------------------------------------ public address

    def public_base_url(self) -> str | None:
        """The address QR codes and posters use: Allgemeines, else
        VB_PUBLIC_BASE_URL; None: automatic (the caller's request origin)."""
        stored = self.repos.app_settings.public_address()
        if stored is not None:
            return stored.address
        return self.core.settings.public_base_url or None

    def public_address(self, origin: str | None = None) -> PublicAddress:
        stored = self.repos.app_settings.public_address()
        env = self.core.settings.public_base_url or None
        source: AddressSource = "setting" if stored else "env" if env else "auto"
        configured = stored.address if stored else env
        effective = configured or (origin.rstrip("/") if origin else None)
        return PublicAddress(
            address=stored.address if stored else None,
            effective=effective,
            source=source,
            check=self._check_state(configured),
        )

    def _check_state(self, configured: str | None) -> AddressCheck:
        if configured is None:
            return AddressCheck(
                status="auto",
                url=None,
                at=None,
                message="Die QR-Codes nehmen die Adresse, unter der die Verwaltung offen ist.",
            )
        last = self.repos.app_settings.public_address_check()
        if last is None or last.url != configured or last.status == "auto":
            return AddressCheck(
                status="unchecked", url=configured, at=None, message="Noch nicht geprüft."
            )
        return AddressCheck(
            status=last.status,  # type: ignore[arg-type]
            url=last.url,
            at=last.at,
            message=last.message,
        )

    def set_public_address(
        self, raw: str | None, *, actor: str, origin: str | None = None
    ) -> PublicAddress:
        """Set the address (None or blank: back to VB_PUBLIC_BASE_URL or
        automatic), then check it. 400 `invalid_public_address`."""
        address = normalize_public_address(raw)
        with self.db.tx():
            stored = self.repos.app_settings.public_address()
            previous = stored.address if stored else None
            if previous != address:
                at = now_iso()
                if address is None:
                    self.repos.app_settings.delete(PUBLIC_ADDRESS_KEY)
                else:
                    self.repos.app_settings.put_public_address(address, by=actor, at=at)
                self.repos.audit.log(
                    actor,
                    "settings.public_address",
                    details={"address": address, "previous": previous},
                    at=at,
                )
        self.check_public_address()
        return self.public_address(origin)

    def check_public_address(self) -> AddressCheck:
        """Fetch `<address>/healthz?probe=<nonce>` and store the outcome
        (nothing to check while the address is automatic)."""
        configured = self.public_base_url()
        if configured is None:
            return self._check_state(None)
        nonce = secrets.token_urlsafe(18)
        status, message = self._probe(configured, nonce)
        check = StoredCheck(status=status, url=configured, at=now_iso(), message=message)
        self.repos.app_settings.put_public_address_check(check)
        return self._check_state(configured)

    def _probe(self, address: str, nonce: str) -> tuple[str, str]:
        try:
            answer = self.fetch_probe(f"{address}/healthz?probe={nonce}")
        except ProbeError as exc:
            return "unreachable", exc.message
        if 300 <= answer.status < 400:
            where = f" nach {answer.location[:120]}" if answer.location else ""
            return "mismatch", f"Leitet weiter{where}. Trag die Zieladresse ein."
        if answer.status != 200:
            return "mismatch", f"Antwortet mit HTTP {answer.status}."
        try:
            data = json.loads(answer.body)
        except ValueError:
            return "mismatch", "Die Antwort kommt nicht von virtubooth."
        mac = data.get("probe_mac") if isinstance(data, dict) else None
        expected = probe_mac(self.core.signer, nonce)
        if not isinstance(mac, str) or not secrets.compare_digest(mac, expected):
            return "mismatch", "Eine andere virtubooth oder ein anderer Server antwortet."
        return "ok", "Erreichbar."
