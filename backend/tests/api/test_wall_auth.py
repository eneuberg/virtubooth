"""Live Wall auth (PLAN-WALL D4, §4.2): the page, login, the cookie and its
scope, the rate limit, the generation counter, the admin bypass."""

from __future__ import annotations

import time

import pytest

from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.auth import COOKIE, LOCK_SECONDS, PASSWORD_KEY

from ..conftest import ORIGIN
from .wall_support import (
    WALL_PASSWORD,
    FakeEnrichment,
    audit_actions,
    set_wall_password,
    wall_login,
    with_wall_page,
)


@pytest.fixture
def fake():
    return FakeEnrichment()


@pytest.fixture
def extensions(demo_extension, fake):
    return [demo_extension, make_extension(enrichment=fake)]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


def set_cookie_header(response) -> str:
    (header,) = [v for k, v in response.headers.multi_items() if k == "set-cookie"]
    return header


def test_page_is_public(client, web_dir):
    r = client.get("/livewall")
    assert r.status_code == 200 and 'data-testid="stub-wall"' in r.text
    assert r.headers["cache-control"] == "private, no-cache" and r.headers["etag"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert client.get("/livewall/", follow_redirects=False).headers["location"] == "/livewall"
    (web_dir / "wall.html").unlink()
    r = client.get("/livewall")
    assert r.status_code == 404 and r.headers["x-vb-page"] == "notfound"


def test_session_states(client, make_client, admin):
    r = client.get("/livewall/api/session")
    assert r.status_code == 409 and r.json()["error"] == "wall_no_password"
    assert "Live-Wall" in r.json()["message"] and r.headers["cache-control"] == "no-store"
    assert wall_login(client).status_code == 409
    # the admin passes without any wall password
    assert admin.get("/livewall/api/session").json() == {"ok": True, "via": "admin"}

    set_wall_password(admin)
    r = client.get("/livewall/api/session")
    assert r.status_code == 401
    assert r.json() == {
        "error": "wall_login_required",
        "message": "Bitte das Live-Wall-Passwort eingeben.",
    }
    for path in ("/livewall/api/feed", "/livewall/api/categories", "/livewall/api/stream"):
        assert client.get(path).json()["error"] == "wall_login_required"

    r = wall_login(client)
    assert r.status_code == 200 and r.json() == {"ok": True, "via": "password"}
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/livewall/api/session").json() == {"ok": True, "via": "password"}
    assert client.get("/livewall/api/feed").status_code == 200


def test_cookie_scope_and_flags(client, admin):
    set_wall_password(admin)
    r = wall_login(client)
    header = set_cookie_header(r)
    assert header.startswith(f"{COOKIE}=")
    parts = {p.strip().split("=")[0].lower(): p.strip() for p in header.split(";")}
    assert parts["path"] == "Path=/livewall"
    assert parts["max-age"] == "Max-Age=2592000"
    assert parts["samesite"].lower() == "samesite=strict"
    assert "httponly" in parts
    assert "secure" not in parts  # plain http in tests
    # the cookie opens nothing outside /livewall
    assert client.get("/api/admin/photos").status_code == 401
    assert client.get("/api/x/wall/admin/config").status_code == 401


def test_cookie_is_secure_over_https(make_client, admin, settings, core):
    core.settings = settings.replace(public_base_url="https://party.example.com")
    set_wall_password(admin)
    c = make_client()
    header = set_cookie_header(wall_login(c))
    assert "secure" in header.lower()


def test_wrong_password_is_audited(client, admin, core):
    set_wall_password(admin)
    r = wall_login(client, "falsch-123")
    assert r.status_code == 403
    assert r.json() == {"error": "wrong_password", "message": "Das Passwort stimmt nicht."}
    assert "set-cookie" not in r.headers
    action, target, _ = audit_actions(core)[0]
    assert action == "wall.login_failed" and target == "ip:testclient"


def test_login_rate_limit(client, admin):
    set_wall_password(admin)
    for _ in range(4):
        assert wall_login(client, "falsch-123").status_code == 403
    assert wall_login(client).status_code == 200
    # the 6th attempt within a minute: refused before the password is checked
    r = wall_login(client)
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1


def test_global_lockout(make_client, admin, core):
    """Review 2, WALL-01: wrong passwords from many addresses lock every wall
    login, the right password included; walls already in and admins keep working."""
    set_wall_password(admin)
    inside = make_client()
    assert wall_login(inside).status_code == 200
    wall = core.extensions["wall"].on_start.__self__  # the extension's Wall
    limits = wall.hub(core).login_limits
    limits.failures = type(limits.failures)(3, 3600)
    codes = []
    for i in range(4):
        # pretend every attempt comes from a different address
        limits.per_minute.reset()
        limits.per_hour.reset()
        r = wall_login(make_client(), f"falsch-{i}-wort")
        codes.append((r.status_code, r.json()["error"]))
    assert codes == [
        (403, "wrong_password"),
        (403, "wrong_password"),
        (429, "login_locked"),
        (429, "login_locked"),
    ]
    limits.per_minute.reset()
    r = wall_login(make_client())
    assert r.status_code == 429 and r.json()["error"] == "login_locked"
    assert 1 <= int(r.headers["retry-after"]) <= LOCK_SECONDS
    assert r.headers["cache-control"] == "no-store" and "set-cookie" not in r.headers
    assert inside.get("/livewall/api/feed").status_code == 200
    assert admin.get("/livewall/api/feed").status_code == 200
    limits.lock.reset()  # the lock is over (or the server restarted)
    assert wall_login(make_client()).status_code == 200


def test_login_needs_same_origin(client, admin):
    set_wall_password(admin)
    r = client.post("/livewall/api/session", json={"password": WALL_PASSWORD})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    r = client.post("/livewall/api/session", json={"password": "x" * 257}, headers=ORIGIN)
    assert r.status_code == 422


def test_password_change_logs_every_wall_out(make_client, admin, core):
    set_wall_password(admin)
    walls = [make_client(), make_client()]
    for w in walls:
        assert wall_login(w).status_code == 200
    gen = core.repos.app_settings.get(PASSWORD_KEY)["gen"]
    set_wall_password(admin, "neues-passwort")
    assert core.repos.app_settings.get(PASSWORD_KEY)["gen"] == gen + 1
    for w in walls:
        assert w.get("/livewall/api/session").status_code == 401
        assert w.get("/livewall/api/feed").status_code == 401
    assert wall_login(walls[0], WALL_PASSWORD).status_code == 403
    assert wall_login(walls[0], "neues-passwort").status_code == 200
    assert walls[0].get("/livewall/api/feed").status_code == 200


def test_admin_logout_keeps_the_password(make_client, admin, core):
    state = set_wall_password(admin)
    wall = make_client()
    wall_login(wall)
    r = admin.post("/api/x/wall/admin/logout", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert wall.get("/livewall/api/session").status_code == 401
    assert wall_login(wall).status_code == 200
    stored = core.repos.app_settings.get(PASSWORD_KEY)
    assert stored["changed_at"] == state["changed_at"] and stored["hash"]
    assert audit_actions(core)[0][:2] == ("wall.logout", "")


def test_clear_password(make_client, admin, core):
    set_wall_password(admin)
    wall = make_client()
    wall_login(wall)
    r = admin.delete("/api/x/wall/admin/password", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"set": False, "changed_at": None}
    assert wall.get("/livewall/api/session").json()["error"] == "wall_no_password"
    assert wall.get("/livewall/api/feed").json()["error"] == "wall_login_required"
    assert wall_login(wall).status_code == 409
    modes = [d.get("mode") for a, _, d in audit_actions(core) if a == "wall.password"]
    assert modes == ["clear", "set"]


def test_set_password_rules(admin, core):
    r = admin.put("/api/x/wall/admin/password", json={"password": "kurz"}, headers=ORIGIN)
    assert r.status_code == 400
    assert r.json() == {
        "error": "wall_password_too_short",
        "message": "Das Passwort braucht mindestens 6 Zeichen.",
    }
    body = set_wall_password(admin, "sechs6")
    assert body["set"] is True and body["changed_at"]
    stored = core.repos.app_settings.get(PASSWORD_KEY)
    assert stored["hash"].startswith("scrypt$15$8$1$") and "sechs6" not in str(stored)
    assert stored["by"].startswith("admin:")
    assert admin.get("/api/x/wall/admin/config").json()["password"] == {
        "set": True,
        "changed_at": body["changed_at"],
    }


def test_screen_logout_clears_only_its_cookie(make_client, admin):
    set_wall_password(admin)
    a, b = make_client(), make_client()
    wall_login(a)
    wall_login(b)
    r = a.delete("/livewall/api/session", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"ok": True}
    header = set_cookie_header(r)
    assert header.startswith(f'{COOKIE}=""') and "Path=/livewall" in header
    assert a.get("/livewall/api/session").status_code == 401
    assert b.get("/livewall/api/session").status_code == 200


def test_forged_and_expired_cookies(make_client, admin, core):
    set_wall_password(admin)
    gen = core.repos.app_settings.get(PASSWORD_KEY)["gen"]
    now = int(time.time())
    cases = {
        "unsigned": f"{gen}.{now}.AAAA",
        "other purpose": core.signer.sign("uid", f"{gen}.{now}"),
        "old generation": core.signer.sign("wall", f"{gen - 1}.{now}"),
        "expired": core.signer.sign("wall", f"{gen}.{now - 31 * 24 * 3600}"),
        "garbage": core.signer.sign("wall", "x.y"),
    }
    for name, value in cases.items():
        c = make_client()
        c.cookies.set(COOKIE, value, path="/livewall")
        assert c.get("/livewall/api/session").status_code == 401, name
    good = make_client()
    good.cookies.set(COOKIE, core.signer.sign("wall", f"{gen}.{now - 3600}"), path="/livewall")
    assert good.get("/livewall/api/session").json()["via"] == "password"


def test_admin_passes_everywhere(admin, client):
    set_wall_password(admin)
    for path in ("/livewall/api/session", "/livewall/api/feed", "/livewall/api/categories"):
        assert admin.get(path).status_code == 200, path
    admin.post("/api/admin/logout", headers=ORIGIN)
    assert admin.get("/livewall/api/feed").status_code == 401
