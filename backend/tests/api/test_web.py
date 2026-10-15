"""Serving the built frontend (VB_WEB_DIR): entries, gate/404 page, assets,
redirects, placeholders and the startup check."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from virtubooth.app import create_app
from virtubooth.settings import ConfigError

from ..conftest import (
    BASE_URL,
    PARTY_TOKEN,
    STUB_CSS,
    STUB_JS,
    STUB_WEB,
    make_settings,
    scan,
)

IMMUTABLE = "public, max-age=31536000, immutable"


def test_guest_entry_needs_access(client):
    r = client.get("/")
    assert r.status_code == 404
    assert r.headers["x-vb-page"] == "gate" and 'data-vb-mode="gate"' in r.text
    assert "Scan den QR-Code" in r.text
    scan(client)
    r = client.get("/")
    assert r.status_code == 200 and 'data-testid="stub-guest-app"' in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "private, no-cache"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_token_entry_redirects_then_serves_the_app(client):
    r = client.get(f"/?t={PARTY_TOKEN}")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "vb_access=" in r.headers["set-cookie"]
    assert client.get("/").status_code == 200


def test_extension_routes(client):
    assert client.get("/x/demo/").status_code == 404  # gate
    scan(client)
    for path in ("/x/demo/", "/x/demo/result", "/x/demo/a/b?debug=1"):
        r = client.get(path)
        assert r.status_code == 200 and 'data-testid="stub-guest-app"' in r.text, path
    # unknown or disabled extension: the not-found page, not the app
    r = client.get("/x/beer/")
    assert r.status_code == 404 and r.headers["x-vb-page"] == "notfound"
    assert 'data-vb-mode="notfound"' in r.text and "Hier ist nichts" in r.text


def test_extension_root_redirects_permanently(client):
    r = client.get("/x/demo")
    assert r.status_code == 308 and r.headers["location"] == "/x/demo/"


def test_gate_and_not_found_are_the_same_file(client, web_dir):
    gate = client.get("/nope")
    assert gate.status_code == 404 and gate.headers["x-vb-page"] == "gate"
    scan(client)
    missing = client.get("/nope")
    assert missing.status_code == 404 and missing.headers["x-vb-page"] == "notfound"
    source = (web_dir / "gate.html").read_text(encoding="utf-8")
    # the theme's stylesheet is linked before </head> (services/theme.py)
    head, _, rest = source.partition("</head>")
    source = (
        head
        + '<link rel="stylesheet" href="/api/theme.css?v='
        + gate.text.split("theme.css?v=")[1].split('"')[0]
        + '"></head>'
        + rest
    ).replace("<html", '<html data-vb-style="party"', 1)  # and its style (services/theme.py)
    assert gate.text == source
    assert missing.text == source.replace('data-vb-mode="gate"', 'data-vb-mode="notfound"')
    # unknown multi-segment paths too
    assert client.get("/some/where").headers["x-vb-page"] == "notfound"


def test_admin_routes(client, admin):
    r = client.get("/admin")
    assert r.status_code == 303 and r.headers["location"] == "/admin/live"
    assert client.get("/admin/").headers["location"] == "/admin/live"
    r = client.get("/admin/login")
    assert r.status_code == 200 and 'data-testid="stub-admin-app"' in r.text
    r = client.get("/admin/manage?tab=gaeste&photo=abc")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login?next=/admin/manage%3Ftab%3Dgaeste%26photo%3Dabc"
    for path in ("/admin/live", "/admin/manage", "/admin/user?id=5", "/admin/manage/export"):
        r = admin.get(path)
        assert r.status_code == 200 and 'data-testid="stub-admin-app"' in r.text, path
        assert r.headers["cache-control"] == "private, no-cache"
    assert admin.get("/admin/.env").status_code == 404


def test_assets_are_immutable_and_public(client):
    r = client.get(f"/assets/{STUB_JS}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == IMMUTABLE
    assert r.headers["vary"] == "Accept-Encoding"
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.content == (STUB_WEB / "assets" / STUB_JS).read_bytes()
    css = client.get(f"/assets/{STUB_CSS}")
    assert css.headers["content-type"].startswith("text/css")
    assert css.headers["cache-control"] == IMMUTABLE
    # fonts and images keep their types
    assert client.get("/assets/a-91b3e7f0.woff2").headers["content-type"] == "font/woff2"
    assert client.get("/assets/a-0c9e4f27.svg").headers["content-type"] == "image/svg+xml"


@pytest.mark.parametrize(
    ("accept", "encoding"),
    [
        ("br, gzip", "br"),
        ("gzip, deflate", "gzip"),
        ("gzip;q=0, br", "br"),
        ("identity", None),
        ("br;q=0, gzip;q=0", None),
    ],
)
def test_assets_are_served_precompressed(client, accept, encoding):
    raw = (STUB_WEB / "assets" / STUB_JS).read_bytes()
    with client.stream("GET", f"/assets/{STUB_JS}", headers={"Accept-Encoding": accept}) as r:
        body = b"".join(r.iter_raw())
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == encoding
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["vary"] == "Accept-Encoding"
    if encoding == "br":
        assert body == (STUB_WEB / "assets" / f"{STUB_JS}.br").read_bytes()
    elif encoding == "gzip":
        assert gzip.decompress(body) == raw
    else:
        assert body == raw


def test_precompressed_siblings_are_not_served_directly(client):
    assert client.get(f"/assets/{STUB_JS}.br").status_code == 404
    assert client.get(f"/assets/{STUB_JS}.gz").status_code == 404


def test_public_root_files(client):
    r = client.get("/boot-check.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "public, max-age=300"
    assert client.get("/icon.svg").headers["content-type"] == "image/svg+xml"
    # the entries are only reachable through their routes
    assert client.get("/index.html").status_code == 404
    assert client.get("/gate.html").status_code == 404


def test_dotfiles_and_traversal_are_blocked(client, web_dir):
    (web_dir / ".vite").mkdir()
    (web_dir / ".vite" / "manifest.json").write_text("{}")
    scan(client)
    for path in (
        "/.vite/manifest.json",
        "/assets/../index.html",
        "/assets/%2e%2e/gate.html",
        "/assets/..%2fgate.html",
        "/x/demo/..%2f..%2fetc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
    ):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "root:" not in r.text


def test_html_is_reread_when_the_build_changes(client, web_dir):
    scan(client)
    assert "stub-guest-app" in client.get("/").text
    index = web_dir / "index.html"
    index.write_text(index.read_text().replace("stub-guest-app", "rebuilt-app") + "\n")
    assert "rebuilt-app" in client.get("/").text


def test_missing_web_dir_fails_at_startup(tmp_path):
    with pytest.raises(ConfigError, match="VB_WEB_DIR"):
        create_app(make_settings(tmp_path / "data", None))
    with pytest.raises(ConfigError, match="VB_WEB_DIR"):
        create_app(make_settings(tmp_path / "data", tmp_path / "nowhere"))
    incomplete = tmp_path / "dist"
    incomplete.mkdir()
    (incomplete / "index.html").write_text("<!doctype html>")
    with pytest.raises(ConfigError, match=r"admin\.html, gate\.html"):
        create_app(make_settings(tmp_path / "data", incomplete))


def test_dev_mode_serves_placeholders(tmp_path: Path):
    app = create_app(make_settings(tmp_path / "data", None, dev=True), extensions=[])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as c:
            gate = c.get("/")
            assert gate.status_code == 404 and gate.headers["x-vb-page"] == "gate"
            assert "Scan den QR-Code" in gate.text
            c.get(f"/?t={PARTY_TOKEN}")
            r = c.get("/")
            assert r.status_code == 200 and "dev-placeholder" in r.text
            assert "<script" not in r.text and "<style" not in r.text
            assert c.get("/admin/login").status_code == 200
            missing = c.get("/nope")
            assert missing.headers["x-vb-page"] == "notfound"
            assert 'data-vb-mode="notfound"' in missing.text
            # the API works as usual
            assert c.get("/healthz").json() == {"ok": True}
            assert c.get("/api/extensions").json()["extensions"] == []
            assert c.get(f"/assets/{STUB_JS}").status_code == 404
    finally:
        app.state.core.db.close()


def test_api_paths_never_get_html(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "http_404", "message": "Not Found"}
    r = client.post("/healthz", headers={"Origin": BASE_URL})
    assert r.status_code == 405 and r.json()["error"] == "http_405"
