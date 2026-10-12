"""Party token gate, guest identity, consent, CSRF, headers."""

from __future__ import annotations

import pytest

from virtubooth.config import ConfigError, Settings
from virtubooth.names import pseudonym

from .conftest import ORIGIN, PARTY_TOKEN, accept_consent, fp, scan


def test_pages_without_token_show_scan_qr(client):
    for path in ("/", "/x/demo/", "/x/demo/app.js", "/nope"):
        r = client.get(path)
        assert r.status_code == 404
        if path != "/nope":
            assert "Scan den QR-Code" in r.text, path


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
    assert "vb_access=" in set_cookie and "HttpOnly" in set_cookie and "samesite=lax" in set_cookie.lower()
    assert client.get("/x/demo/").status_code == 200
    assert client.get("/x/demo/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/").status_code == 200


def test_rotating_party_token_invalidates_access(client, app, settings):
    scan(client)
    assert client.get("/").status_code == 200
    from dataclasses import replace

    app.state.core.settings = replace(settings, party_token="a-completely-new-token-xyz")
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
        "/api/consent",
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
    assert core.repo.list_users()[0].fp_hash == fp()["hash"]


def test_consent_requires_accept_true(client):
    scan(client)
    r = client.post("/api/consent", json={"accept": False, "version": "1"}, headers=ORIGIN)
    assert r.status_code == 422


def test_consent_version_mismatch(client):
    scan(client)
    r = client.post("/api/consent", json={"accept": True, "version": "0"}, headers=ORIGIN)
    assert r.status_code == 409
    assert r.json()["error"] == "consent_outdated"


def test_consent_is_idempotent_for_known_device(client, core):
    scan(client)
    accept_consent(client)
    accept_consent(client)
    assert len(core.repo.list_users()) == 1


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
    from virtubooth.identity import normalize_instagram

    assert normalize_instagram(raw) == expected


@pytest.mark.parametrize("raw", ["has space", "<script>", "a" * 31, "dots..dots", "ümlaut"])
def test_instagram_rejects_garbage(raw):
    from virtubooth.errors import ApiError
    from virtubooth.identity import normalize_instagram

    with pytest.raises(ApiError):
        normalize_instagram(raw)


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
    r = c.post("/api/consent", json={"accept": True, "version": "1"}, headers=ORIGIN)
    assert r.status_code == 429
    assert "retry-after" in r.headers


def test_csrf_origin_check(guest):
    g = guest()
    assert g.patch("/api/me", json={"instagram": "x"}).status_code == 403  # no Origin
    r = g.patch("/api/me", json={"instagram": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"] == "bad_origin"
    r = g.patch("/api/me", json={"instagram": "x"}, headers={"Referer": "http://testserver/x/demo/"})
    assert r.status_code == 200


def test_origin_normalization():
    from starlette.requests import Request

    from virtubooth.security import origin_allowed

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
    assert client.post("/api/identify", json={}, headers=ORIGIN).headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path", ["/x/demo/../../etc/passwd", "/x/demo/%2e%2e/%2e%2e/etc/passwd", "/x/demo/.secret", "/x/nope/"]
)
def test_static_traversal_blocked(client, path, demo_extension):
    (demo_extension.static_dir / ".secret").write_text("nope")
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
    base = dict(party_token=PARTY_TOKEN, admin_password="x" * 12, secret_key="y" * 32, data_dir=tmp_path)
    Settings(**base)
    for key, bad in (("party_token", "short"), ("party_token", "has spaces in it!!!"),
                     ("admin_password", "short"), ("secret_key", "short"), ("cookie_secure", "maybe")):
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
