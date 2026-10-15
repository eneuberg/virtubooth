"""Allgemeines → Öffentliche Adresse (PLAN-NIGHT N14): the setting, its check
(`<address>/healthz?probe=<nonce>` must answer this server's probe_mac), and
where it is used (QR codes API, Live-Wall code, exports list).

The probe is a fake fetcher here, plus one real loopback check against a live
uvicorn of the test app."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from fastapi import FastAPI

from virtubooth.services import host_settings as hs
from virtubooth.services.host_settings import ProbeAnswer, ProbeError, normalize_public_address

from ..conftest import ORIGIN

ADDRESS = "https://party.example.com"


def put(admin, address):
    return admin.put(
        "/api/admin/settings/public-address", json={"address": address}, headers=ORIGIN
    )


def check(admin):
    r = admin.post("/api/admin/settings/public-address/check", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


class Fake:
    """A fetcher that answers like this server (or as told), and records URLs."""

    def __init__(self, core, mode: str = "ok") -> None:
        self.core = core
        self.mode = mode
        self.urls: list[str] = []

    def __call__(self, url: str) -> ProbeAnswer:
        self.urls.append(url)
        nonce = parse_qs(urlsplit(url).query)["probe"][0]
        if self.mode == "ok":
            mac = hs.probe_mac(self.core.signer, nonce)
            return ProbeAnswer(200, f'{{"ok":true,"probe_mac":"{mac}"}}'.encode())
        if self.mode == "other":
            return ProbeAnswer(200, b'{"ok":true,"probe_mac":"AAAAAAAAAAAAAAAA"}')
        if self.mode == "html":
            return ProbeAnswer(200, b"<html>hello</html>")
        if self.mode == "redirect":
            return ProbeAnswer(301, b"", location="https://elsewhere.example/healthz")
        if self.mode == "404":
            return ProbeAnswer(404, b"")
        raise ProbeError("Verbindung abgelehnt.")


@pytest.fixture
def fake(core) -> Fake:
    f = Fake(core)
    core.services.host_settings.fetch_probe = f
    return f


# ------------------------------------------------------------ normalising


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("   ", None),
        (" HTTPS://Party.Example.com/ ", "https://party.example.com"),
        ("http://192.168.1.20:8080", "http://192.168.1.20:8080"),
        ("https://example.com/party/", "https://example.com/party"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_normalise(raw, expected):
    assert normalize_public_address(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "party.example.com",
        "ftp://x.example",
        "javascript:alert(1)",
        "https://x.example/?a=1",
        "https://x.example/#top",
        "https://",
        "https://user:pw@x.example",
        "https://x.example:99999",
        "https://x.exa mple",
        "https://x.example/\npath",
    ],
)
def test_invalid_addresses(admin, core, raw):
    r = put(admin, raw)
    assert r.status_code == 400 and r.json()["error"] == "invalid_public_address", raw
    assert core.repos.app_settings.public_address() is None


def test_too_long_is_refused(admin):
    r = put(admin, "https://" + "x" * 300 + ".example")
    assert r.status_code in (400, 422)


# ------------------------------------------------------------ the setting


def test_set_checks_audits_and_is_used(admin, core, fake):
    r = put(admin, " https://Party.example.com/ ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["address"] == body["effective"] == ADDRESS
    assert body["source"] == "setting"
    assert body["check"]["status"] == "ok" and body["check"]["url"] == ADDRESS
    assert body["check"]["at"] and body["check"]["message"] == "Erreichbar."
    assert fake.urls[0].startswith(f"{ADDRESS}/healthz?probe=")
    assert admin.get("/api/admin/settings").json()["public_address"] == body
    entry = core.repos.audit.list(limit=1)[0]
    assert entry.action == "settings.public_address"
    assert entry.details == {"address": ADDRESS, "previous": None}
    # used by the QR codes (and posters, which read the codes API) and the exports form
    assert admin.get("/api/admin/codes").json()["base_url"] == ADDRESS
    assert admin.get("/api/admin/exports").json()["public_base_url"] == ADDRESS


def test_setting_overrides_env_and_reset(admin, core, fake):
    core.settings = core.settings.replace(public_base_url="https://env.example")
    state = admin.get("/api/admin/settings").json()["public_address"]
    assert state["source"] == "env" and state["effective"] == "https://env.example"
    assert state["address"] is None and state["check"]["status"] == "unchecked"
    assert admin.get("/api/admin/codes").json()["base_url"] == "https://env.example"

    assert put(admin, ADDRESS).json()["source"] == "setting"
    assert admin.get("/api/admin/codes").json()["base_url"] == ADDRESS

    back = put(admin, "").json()
    assert back["source"] == "env" and back["address"] is None
    assert back["check"]["status"] == "ok" and back["check"]["url"] == "https://env.example"
    assert admin.get("/api/admin/codes").json()["base_url"] == "https://env.example"
    entry = core.repos.audit.list(limit=1)[0]
    assert entry.details == {"address": None, "previous": ADDRESS}


def test_auto_needs_no_check(admin, core, fake):
    assert check(admin)["status"] == "auto"
    assert fake.urls == []
    assert admin.get("/api/admin/codes").json()["base_url"] is None


def test_unchanged_address_is_not_audited_again(admin, core, fake):
    put(admin, ADDRESS)
    put(admin, ADDRESS + "/")
    actions = [e.action for e in core.repos.audit.list(limit=10)]
    assert actions.count("settings.public_address") == 1
    assert len(fake.urls) == 2  # but checked each time


@pytest.mark.parametrize(
    ("mode", "status", "words"),
    [
        ("other", "mismatch", "anderer Server"),
        ("html", "mismatch", "nicht von virtubooth"),
        ("redirect", "mismatch", "nach https://elsewhere.example."),
        ("404", "mismatch", "HTTP 404"),
        ("down", "unreachable", "abgelehnt"),
    ],
)
def test_failed_checks_never_block_saving(admin, core, fake, mode, status, words):
    fake.mode = mode
    r = put(admin, ADDRESS)
    assert r.status_code == 200
    assert r.json()["address"] == ADDRESS
    got = r.json()["check"]
    assert got["status"] == status and words in got["message"], got
    # a later check that works replaces it
    fake.mode = "ok"
    assert check(admin)["status"] == "ok"


def test_changed_address_is_unchecked_until_checked(admin, core, fake):
    put(admin, ADDRESS)
    core.settings = core.settings.replace(public_base_url="https://env.example")
    core.repos.app_settings.delete("public_address")
    state = admin.get("/api/admin/settings").json()["public_address"]
    assert state["check"] == {
        "status": "unchecked", "url": "https://env.example", "at": None,
        "message": "Noch nicht geprüft.",
    }  # fmt: skip


def test_wall_qr_uses_the_address(admin, core, fake):
    from virtubooth.extensions.wall.config import WallConfig
    from virtubooth.extensions.wall.feed import wall_qr

    config = WallConfig()
    config.overlay.qr = True
    qr = wall_qr(core, config, "http://lan.local:8000/")
    assert qr is not None and qr.url.startswith("http://lan.local:8000/?t=")
    put(admin, ADDRESS)
    qr = wall_qr(core, config, "http://lan.local:8000/")
    assert qr is not None and qr.url.startswith(f"{ADDRESS}/?t=")


def test_settings_need_the_admin(client):
    assert client.get("/api/admin/settings").status_code == 401
    r = client.post("/api/admin/settings/public-address/check", headers=ORIGIN)
    assert r.status_code == 401
    r = client.put("/api/admin/settings/public-address", json={"address": None}, headers=ORIGIN)
    assert r.status_code == 401


# ------------------------------------------------------------ /healthz probe


def test_healthz_probe(client, core):
    assert client.get("/healthz").json() == {"ok": True}
    body = client.get("/healthz?probe=abc_DEF-123").json()
    assert body == {"ok": True, "probe_mac": hs.probe_mac(core.signer, "abc_DEF-123")}
    assert len(body["probe_mac"]) == 16
    for bad in ("a" * 65, "a.b", "a%7Cb"):
        assert client.get(f"/healthz?probe={bad}").status_code == 422, bad
    assert client.head("/healthz").status_code == 200


# --------------------------------------------------- one real loopback check


@pytest.fixture
def live_url(app: FastAPI) -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                       timeout_graceful_shutdown=1)
    )  # fmt: skip
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def test_real_loopback_check(admin, live_url):
    r = put(admin, live_url)
    assert r.status_code == 200, r.text
    assert r.json()["check"]["status"] == "ok", r.json()


def test_real_fetcher_unreachable_and_foreign():
    # a port nobody listens on
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(ProbeError):
        hs.fetch_probe(f"http://127.0.0.1:{port}/healthz?probe=x")
