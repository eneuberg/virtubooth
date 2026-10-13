"""Party token gate, guest identity, consent, CSRF, headers."""

from __future__ import annotations

import pytest

from virtubooth.domain.names import pseudonym
from virtubooth.settings import ConfigError, Settings

from ..conftest import ORIGIN, PARTY_TOKEN, STUB_JS, accept_consent, fp, scan


def test_pages_without_token_show_scan_qr(client):
    for path in ("/", "/x/demo/", "/x/demo/app.js", "/nope", "/x/unknown/"):
        r = client.get(path)
        assert r.status_code == 404
        assert "Scan den QR-Code" in r.text, path


def test_unknown_page_with_access_is_plain_not_found(client):
    scan(client)
    r = client.get("/nope")
    assert r.status_code == 404
    assert "Hier ist nichts" in r.text
    # gate.html in its not-found mode (the CSS shows the matching text)
    assert r.headers["x-vb-page"] == "notfound"
    assert 'data-vb-mode="notfound"' in r.text and 'data-vb-mode="gate"' not in r.text


def test_wrong_token_shows_gate_and_sets_no_cookie(client):
    r = client.get("/?t=definitely-not-the-token")
    assert r.status_code == 404
    assert "Scan den QR-Code" in r.text
    assert "vb_access" not in r.cookies


def test_token_sets_cookie_and_strips_itself(client):
    r = client.get(f"/x/demo/?t={PARTY_TOKEN}&debug=1")
    assert r.status_code == 303
    assert r.headers["location"] == "/x/demo/?debug=1"
    set_cookie = r.headers["set-cookie"]
    assert (
        "vb_access=" in set_cookie
        and "HttpOnly" in set_cookie
        and "samesite=lax" in set_cookie.lower()
    )
    assert client.get("/x/demo/").status_code == 200
    # the pages' code is served from /assets/ (public, built by the frontend)
    assert client.get(f"/assets/{STUB_JS}").headers["content-type"].startswith("text/javascript")
    assert client.get("/").status_code == 200


def test_rotating_party_token_invalidates_access(client, app, settings):
    scan(client)
    assert client.get("/").status_code == 200
    app.state.core.settings = settings.replace(party_token="a-completely-new-token-xyz")
    assert client.get("/").status_code == 404


def test_api_without_access(client):
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 404
    assert r.json()["error"] == "scan_qr"
    r = client.get("/api/extensions")
    assert r.json()["error"] == "scan_qr"


def test_identify_consent_flow(client, core):
    scan(client)
    r = client.post("/api/identify", json={"fp": fp()}, headers=ORIGIN)
    body = r.json()
    assert body["state"] == "needs_consent"
    assert body["consent"]["version"] == "1"
    assert "@testparty" in " ".join(body["consent"]["paragraphs"])

    r = client.post(
        "/api/join",
        json={"accept": True, "version": "1", "instagram": "@Party.Animal", "fp": fp()},
        headers=ORIGIN,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "ok"
    assert body["user"]["instagram"] == "party.animal"
    assert body["user"]["name"].endswith("#1")
    assert "vb_uid=" in r.headers["set-cookie"]

    r = client.post("/api/identify", json={"fp": fp()}, headers=ORIGIN)
    assert r.json()["state"] == "ok"
    assert core.repos.users.list()[0].fp_hash == fp()["hash"]


def test_consent_requires_accept_true(client):
    scan(client)
    r = client.post("/api/join", json={"accept": False, "version": "1"}, headers=ORIGIN)
    assert r.status_code == 422


def test_consent_requires_a_fingerprint(client, core):
    """Leaving the fingerprint out must not skip the fingerprint-ban check."""
    scan(client)
    r = client.post("/api/join", json={"accept": True, "version": "1"}, headers=ORIGIN)
    assert r.status_code == 422
    assert core.repos.users.list() == []


def test_consent_version_mismatch(client):
    scan(client)
    r = client.post("/api/join", json={"accept": True, "version": "0", "fp": fp()}, headers=ORIGIN)
    assert r.status_code == 409
    assert r.json()["error"] == "consent_outdated"


def test_consent_is_idempotent_for_known_device(client, core):
    scan(client)
    accept_consent(client)
    accept_consent(client)
    assert len(core.repos.users.list()) == 1


def test_uid_token_restores_identity_when_cookie_is_lost(client):
    scan(client)
    token = accept_consent(client)["uid_token"]
    client.cookies.delete("vb_uid")
    r = client.post("/api/identify", json={"uid": token}, headers=ORIGIN)
    assert r.json()["state"] == "ok"
    assert "vb_uid=" in r.headers["set-cookie"]


def test_forged_uid_token_is_ignored(client, guest):
    victim = guest()
    victim_token = victim.post("/api/identify", json={}, headers=ORIGIN).json()["uid_token"]
    public_id = victim_token.rsplit(".", 1)[0]
    scan(client)
    r = client.post("/api/identify", json={"uid": f"{public_id}.forgedsignature"}, headers=ORIGIN)
    assert r.json()["state"] == "needs_consent"
    client.cookies.set("vb_uid", f"{public_id}.forged")
    assert client.post("/api/identify", json={}, headers=ORIGIN).json()["state"] == "needs_consent"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Foo.Bar", "foo.bar"),
        ("https://www.instagram.com/some_one/?hl=de", "some_one"),
        ("  ", None),
        ("", None),
    ],
)
def test_instagram_normalization(raw, expected):
    from virtubooth.services.identity import normalize_instagram

    assert normalize_instagram(raw) == expected


@pytest.mark.parametrize("raw", ["has space", "<script>", "a" * 31, "dots..dots", "ümlaut"])
def test_instagram_rejects_garbage(raw):
    from virtubooth.core.errors import ApiError
    from virtubooth.services.identity import normalize_instagram

    with pytest.raises(ApiError):
        normalize_instagram(raw)


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ("a" * 31, "höchstens 30 Zeichen, deiner hat 31"),
        ("@" + "b" * 40, "deiner hat 40"),
        ("jürgen.k", "keine Umlaute"),
        ("GROSSE_STRAßE", "keine Umlaute"),
        ("josé", "keine Akzente"),
        ("has space", "keine Leerzeichen"),
        ("dots..dots", "Zwei Punkte"),
        ("partyqueen👑", "nur Buchstaben (a bis z), Zahlen, Punkt und Unterstrich"),
    ],
)
def test_instagram_errors_say_what_is_wrong(raw, says):
    from virtubooth.core.errors import ApiError
    from virtubooth.services.identity import normalize_instagram

    with pytest.raises(ApiError) as exc:
        normalize_instagram(raw)
    assert exc.value.code == "invalid_instagram"
    assert says in exc.value.message


def test_join_from_a_second_tab_adds_a_missing_handle(client, core):
    """Two tabs show the join dialog on a first visit. The first is accepted
    without a handle, then the second with one: store it, don't drop it."""
    scan(client)
    first = accept_consent(client)
    assert first["already_joined"] is False and first["user"]["instagram"] is None
    second = accept_consent(client, instagram="@Tab.B")
    assert second["already_joined"] is True and second["instagram_kept"] is False
    assert second["user"]["instagram"] == "tab.b"
    assert second["user"]["name"] == first["user"]["name"]
    users = core.repos.users.list()
    assert len(users) == 1 and users[0].instagram == "tab.b"


def test_join_from_a_second_tab_keeps_the_existing_handle(client, core):
    scan(client)
    accept_consent(client, instagram="tab.a")
    other = accept_consent(client, instagram="@tab.b")
    assert other["already_joined"] is True and other["instagram_kept"] is True
    assert other["user"]["instagram"] == "tab.a"
    assert accept_consent(client, instagram="@TAB.A")["instagram_kept"] is False
    assert accept_consent(client)["user"]["instagram"] == "tab.a"
    assert core.repos.users.list()[0].instagram == "tab.a"


def test_join_from_a_second_tab_checks_the_handle(client, core):
    scan(client)
    accept_consent(client)
    r = client.post(
        "/api/join",
        json={"accept": True, "version": "1", "instagram": "jürgen", "fp": fp()},
        headers=ORIGIN,
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_instagram"
    assert core.repos.users.list()[0].instagram is None


def test_banned_device_cannot_set_a_handle_by_joining_again(client, core):
    scan(client)
    accept_consent(client)
    user = core.repos.users.list()[0]
    core.services.moderation.ban_user(user.id, reason="test", actor="pytest")
    r = accept_consent(client, instagram="sneaky")
    assert r["state"] == "banned" and r["user"]["instagram"] is None
    assert core.repos.users.get(user.id).instagram is None


def test_update_instagram(guest):
    g = guest()
    r = g.patch("/api/me", json={"instagram": "@new_handle"}, headers=ORIGIN)
    assert r.json()["user"]["instagram"] == "new_handle"
    r = g.patch("/api/me", json={"instagram": None}, headers=ORIGIN)
    assert r.json()["user"]["instagram"] is None
    r = g.patch("/api/me", json={"instagram": "bad handle"}, headers=ORIGIN)
    assert r.status_code == 400


def test_new_user_rate_limit(make_client, core):
    core.limits.new_user_ip = type(core.limits.new_user_ip)(2, 600)
    for _ in range(2):
        c = make_client()
        scan(c)
        accept_consent(c)
    c = make_client()
    scan(c)
    r = c.post("/api/join", json={"accept": True, "version": "1", "fp": fp()}, headers=ORIGIN)
    assert r.status_code == 429
    assert "retry-after" in r.headers


def test_csrf_origin_check(guest):
    g = guest()
    assert g.patch("/api/me", json={"instagram": "x"}).status_code == 403  # no Origin
    r = g.patch("/api/me", json={"instagram": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"] == "bad_origin"
    r = g.patch(
        "/api/me", json={"instagram": "x"}, headers={"Referer": "http://testserver/x/demo/"}
    )
    assert r.status_code == 200


def test_origin_normalization():
    from starlette.requests import Request

    from virtubooth.core.security import origin_allowed

    s = Settings(
        party_token=PARTY_TOKEN,
        admin_password="x" * 12,
        secret_key="y" * 32,
        data_dir=__import__("pathlib").Path("/tmp"),
        allowed_origins=("https://alias.example",),
    )

    def req(host: str, origin: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
            }
        )

    assert origin_allowed(req("party.example", "https://party.example"), s)
    assert origin_allowed(req("party.example:443", "https://party.example"), s)
    assert origin_allowed(req("localhost:8000", "http://localhost:8000"), s)
    assert not origin_allowed(req("localhost:8000", "http://localhost:9000"), s)
    assert not origin_allowed(req("party.example", "https://party.example.evil.com"), s)
    assert not origin_allowed(req("party.example", "null"), s)
    assert origin_allowed(req("internal:8000", "https://alias.example"), s)


def test_security_headers(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "camera=(self)" in r.headers["permissions-policy"]
    assert (
        client.post("/api/identify", json={}, headers=ORIGIN).headers["cache-control"] == "no-store"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/x/demo/../../etc/passwd",
        "/x/demo/%2e%2e/%2e%2e/etc/passwd",
        "/x/demo/.secret",
        "/x/nope/",
        "/.secret",
        "/assets/.secret",
        "/assets/%2e%2e/.secret",
        "/assets/%2e%2e/index.html",
    ],
)
def test_static_traversal_blocked(client, path, web_dir):
    (web_dir / ".secret").write_text("nope")
    (web_dir / "assets" / ".secret").write_text("nope")
    scan(client)
    r = client.get(path)
    assert r.status_code == 404
    assert "root:" not in r.text and "nope" != r.text


def test_extensions_listing(client):
    scan(client)
    body = client.get("/api/extensions").json()
    assert body["party_name"] == "Testparty"
    assert body["extensions"][0]["id"] == "demo"
    assert body["extensions"][0]["url"] == "/x/demo/"


def test_settings_validation(tmp_path):
    base = dict(
        party_token=PARTY_TOKEN, admin_password="x" * 12, secret_key="y" * 32, data_dir=tmp_path
    )
    Settings(**base)
    for key, bad in (
        ("party_token", "short"),
        ("party_token", "has spaces in it!!!"),
        ("admin_password", "short"),
        ("secret_key", "short"),
        ("cookie_secure", "maybe"),
    ):
        with pytest.raises(ConfigError):
            Settings(**(base | {key: bad}))


def test_settings_from_env(tmp_path):
    env = {
        "VB_PARTY_TOKEN": PARTY_TOKEN,
        "VB_ADMIN_PASSWORD": "x" * 12,
        "VB_SECRET_KEY": "y" * 32,
        "VB_DATA_DIR": str(tmp_path),
        "VB_EXTENSIONS": "beer, booth",
        "VB_UPLOADS_PER_USER_PER_MIN": "3",
    }
    s = Settings.from_env(env)
    assert s.extensions == ("beer", "booth")
    assert s.uploads_per_user_per_min == 3
    with pytest.raises(ConfigError):
        Settings.from_env({})


def test_pseudonyms_are_grammatical_and_unique():
    names = {pseudonym(i) for i in range(1, 200)}
    assert len(names) == 199
    assert pseudonym(1).endswith("#1")
    for name in names:
        adjective, animal = name.split(" ")[:2]
        assert adjective[-1] in "res" and animal[0].isupper()


def test_access_log_masks_token_and_skips_healthz():
    import logging

    from virtubooth.core.logs import AccessLogFilter

    f = AccessLogFilter()

    def record(path: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:5", "GET", path, "1.1", 303),
            None,
        )

    r = record(f"/x/beer/?debug=1&t={PARTY_TOKEN}")
    assert f.filter(r)
    assert PARTY_TOKEN not in r.getMessage() and "t=***" in r.getMessage()
    assert not f.filter(record("/healthz"))


def test_healthz_head(client):
    assert client.head("/healthz").status_code == 200


def test_discover_respects_explicit_order():
    from virtubooth.extensions.sdk import discover_extensions

    everything = [e.id for e in discover_extensions()]
    assert discover_extensions(list(reversed(everything))) == list(reversed(discover_extensions()))
    assert [e.id for e in discover_extensions(["beer", "beer"])] == ["beer"]
    assert [e.id for e in discover_extensions(["booth", "beer"])] == ["booth", "beer"]
    assert [e.id for e in discover_extensions()] == ["beer", "booth"]
    with pytest.raises(ConfigError):
        discover_extensions(["nope"])


def test_token_entry_never_redirects_off_site(client):
    r = client.get(f"http://testserver//evil.example/?t={PARTY_TOKEN}")
    assert r.status_code == 303
    assert r.headers["location"] == "/evil.example/"


def test_json_bodies_are_capped(client, guest):
    r = client.post(
        "/api/admin/login",
        content=b'{"password": "' + b"x" * 200_000 + b'"}',
        headers=ORIGIN | {"Content-Type": "application/json"},
    )
    assert r.status_code == 413
    r = client.post(
        "/api/admin/login",
        content=(c for c in [b'{"password": "x"}']),
        headers=ORIGIN | {"Content-Type": "application/json"},
    )
    assert r.status_code == 411  # chunked: unknown length
    g = guest()
    assert g.patch("/api/me", json={"instagram": "ok"}, headers=ORIGIN).status_code == 200


def test_api_budget_is_per_device_for_guests(guest, make_client, core):
    core.limits.api_guest = type(core.limits.api_guest)(5, 60)
    noisy, calm = guest(), guest(fp_n=2)
    codes = [noisy.post("/api/identify", json={}, headers=ORIGIN).status_code for _ in range(8)]
    assert 429 in codes
    # same IP (testclient), different device: unaffected
    assert calm.post("/api/identify", json={}, headers=ORIGIN).status_code == 200


def test_https_gets_hsts_and_secure_cookies(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        r = c.get(f"/?t={PARTY_TOKEN}")
        assert "Secure" in r.headers["set-cookie"]
        assert r.headers["strict-transport-security"] == "max-age=31536000"
    with TestClient(app, base_url="http://testserver", follow_redirects=False) as c:
        r = c.get(f"/?t={PARTY_TOKEN}")
        assert "Secure" not in r.headers["set-cookie"]
        assert "strict-transport-security" not in r.headers


def test_https_public_url_makes_auto_cookies_secure(client, core):
    core.settings = core.settings.replace(public_base_url="https://party.example")
    r = client.get(f"/?t={PARTY_TOKEN}")
    assert "Secure" in r.headers["set-cookie"]
