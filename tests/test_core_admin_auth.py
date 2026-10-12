"""Admin login, sessions, page gating."""

from __future__ import annotations

from dataclasses import replace

from virtubooth.context import Limits

from .conftest import ADMIN_PASSWORD, ORIGIN


def login(client, password=ADMIN_PASSWORD, headers=ORIGIN):
    return client.post("/api/admin/login", json={"password": password}, headers=headers)


def test_login_logout(client):
    assert client.get("/api/admin/session").json() == {"authenticated": False}
    r = login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "vb_admin=" in cookie and "HttpOnly" in cookie and "samesite=strict" in cookie.lower()
    assert client.get("/api/admin/session").json() == {"authenticated": True}
    assert client.post("/api/admin/logout", headers=ORIGIN).status_code == 200
    assert client.get("/api/admin/session").json() == {"authenticated": False}


def test_stolen_cookie_dies_on_logout(client, make_client):
    login(client)
    token = client.cookies.get("vb_admin")
    thief = make_client()
    thief.cookies.set("vb_admin", token)
    assert thief.get("/api/admin/session").json()["authenticated"]
    client.post("/api/admin/logout", headers=ORIGIN)
    assert not thief.get("/api/admin/session").json()["authenticated"]


def test_wrong_password_and_rate_limit(client, core):
    for _ in range(5):
        r = login(client, "wrong-password-123")
        assert r.status_code == 401 and r.json()["error"] == "wrong_password"
    r = login(client)  # even the right password waits now
    assert r.status_code == 429
    assert "admin.login_failed" in {e["action"] for e in core.repo.list_audit()}


def test_global_lockout(make_client, core):
    core.limits.login_failures_global = type(core.limits.login_failures_global)(3, 3600)
    for i in range(3):
        c = make_client()
        # pretend every attempt comes from a different IP
        core.limits.login_ip.reset()
        core.limits.login_ip_hourly.reset()
        assert login(c, f"wrong-{i}-password").status_code == 401
    r = login(make_client())
    assert r.status_code == 429 and r.json()["error"] == "login_locked"


def test_password_change_ends_sessions(client, core):
    login(client)
    assert client.get("/api/admin/session").json()["authenticated"]
    core.settings = replace(core.settings, admin_password="a-brand-new-password")
    assert not client.get("/api/admin/session").json()["authenticated"]


def test_login_needs_same_origin(client):
    assert login(client, headers={}).status_code == 403
    assert login(client, headers={"Origin": "https://evil.example"}).status_code == 403


def test_admin_pages_redirect_to_login(client):
    r = client.get("/admin/live")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login?next=/admin/live"
    assert client.get("/admin").headers["location"] == "/admin/live"


def test_admin_api_requires_session(client):
    # any route under the admin router; unknown ones are 404 only after auth
    r = client.get("/api/admin/session")
    assert r.status_code == 200


def test_guest_cannot_use_admin_cookie_name(guest):
    g = guest()
    g.cookies.set("vb_admin", "x" * 43)
    assert not g.get("/api/admin/session").json()["authenticated"]
    g.cookies.set("vb_admin", "x" * 500)
    assert not g.get("/api/admin/session").json()["authenticated"]


def test_limits_reset():
    from virtubooth.config import Settings

    limits = Limits.from_settings(
        Settings(party_token="p" * 16, admin_password="a" * 12, secret_key="s" * 32, data_dir=__import__("pathlib").Path("/tmp"))
    )
    for _ in range(5):
        limits.login_ip.hit("ip")
    assert not limits.login_ip.hit("ip")
    limits.reset()
    assert limits.login_ip.hit("ip")
