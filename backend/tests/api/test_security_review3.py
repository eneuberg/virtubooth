"""Regression tests for security review 3 (docs/overhaul/SECURITY_REVIEW.md,
"Review 3: PSA"), one section per finding."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virtubooth.core.security import SECURE_UID_COOKIE, UID_COOKIE

from ..conftest import JPEG, PARTY_TOKEN, fp, jpeg

TLS_BASE = "https://party.example"
TLS_ORIGIN = {"Origin": TLS_BASE}

# ============================================== COOKIE-01 planted guest id


@pytest.fixture
def tls(app: FastAPI) -> Iterator[TestClient]:
    """Clients of the app as reached over TLS (https://party.example)."""
    clients: list[TestClient] = []

    def make() -> TestClient:
        c = TestClient(app, base_url=TLS_BASE, follow_redirects=False)
        c.__enter__()
        clients.append(c)
        return c

    yield make  # type: ignore[misc]
    for c in clients:
        c.__exit__(None, None, None)


def _join_tls(c: TestClient, n: int) -> dict[str, object]:
    assert c.get(f"/?t={PARTY_TOKEN}").status_code == 303
    r = c.post("/api/join", json={"accept": True, "version": "1", "fp": fp(n)}, headers=TLS_ORIGIN)
    assert r.status_code == 201, r.text
    return r.json()


def test_over_tls_the_guest_id_cookie_is_host_prefixed(tls):
    c = tls()
    r_join = _join_tls(c, 1)
    assert c.cookies.get(SECURE_UID_COOKIE) == r_join["uid_token"]
    assert c.cookies.get(UID_COOKIE) is None
    r = c.post("/api/identify", json={"fp": fp(1)}, headers=TLS_ORIGIN)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SECURE_UID_COOKIE}=")
    assert "Secure" in cookie and "Path=/" in cookie and "Domain" not in cookie


def test_over_tls_a_planted_plain_guest_id_is_ignored(tls):
    """The PoC: the attacker's own signed id, planted as `vb_uid` (sibling
    subdomain, or a plain-http answer on the venue Wi-Fi), must not make a new
    guest upload into the attacker's identity."""
    attacker = tls()
    planted = str(_join_tls(attacker, 1)["uid_token"])
    victim = tls()
    victim.cookies.set(UID_COOKIE, planted, domain="party.example")
    assert victim.get(f"/?t={PARTY_TOKEN}").status_code == 303
    r = victim.post("/api/identify", json={"fp": fp(2)}, headers=TLS_ORIGIN)
    assert r.json()["state"] == "needs_consent"
    # no upload into anyone's identity without joining
    r = victim.post("/api/x/demo/upload", content=jpeg(), headers={**JPEG, **TLS_ORIGIN})
    assert r.status_code == 401
    assert attacker.get("/api/me/photos").json()["photos"] == []


def test_the_localstorage_copy_moves_a_guest_to_the_prefixed_cookie(tls):
    """A guest whose cookie is the plain one from before the change keeps the
    identity: the frontend sends the localStorage copy on identify."""
    c = tls()
    token = str(_join_tls(c, 1)["uid_token"])
    c.cookies.clear()
    c.cookies.set(UID_COOKIE, token, domain="party.example")
    assert c.get(f"/?t={PARTY_TOKEN}").status_code == 303
    r = c.post("/api/identify", json={"fp": fp(1), "uid": token}, headers=TLS_ORIGIN)
    assert r.json()["state"] == "ok"
    assert c.cookies.get(SECURE_UID_COOKIE) == token
    assert c.get("/api/me/photos").status_code == 200


def test_plain_http_keeps_the_plain_name(guest):
    c = guest()
    assert c.cookies.get(UID_COOKIE) is not None
    assert c.cookies.get(SECURE_UID_COOKIE) is None
