"""Admin pages: gating and serving the admin app (admin.html of the build).

The checks of the old hand-written admin files (CSP-safe markup, unsafe DOM
APIs, the live screen's limits) moved: built HTML and frontend sources are
checked in tests/unit/test_frontend_contract.py, the admin UI's behaviour in
tests/e2e/admin/.
"""

from __future__ import annotations

import pytest

from ..conftest import STUB_CSS, STUB_JS

PAGES = ["live", "manage", "user"]


@pytest.mark.parametrize("page", PAGES)
def test_pages_need_admin(client, guest, page):
    r = client.get(f"/admin/{page}")
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/login?next=/admin/{page}"
    assert guest().get(f"/admin/{page}").status_code == 303


@pytest.mark.parametrize("page", PAGES)
def test_pages_served_to_admin(admin, page):
    r = admin.get(f"/admin/{page}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'data-testid="stub-admin-app"' in r.text  # admin.html: the app routes itself
    assert f'src="/assets/{STUB_JS}"' in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "private, no-cache"


def test_login_page_is_public(client):
    r = client.get("/admin/login?next=/admin/manage")
    assert r.status_code == 200 and 'data-testid="stub-admin-app"' in r.text


def test_assets_are_public_with_right_types(client):
    r = client.get(f"/assets/{STUB_JS}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert client.get(f"/assets/{STUB_CSS}").headers["content-type"].startswith("text/css")
    assert client.get("/assets/%2e%2e/index.html").status_code == 404
    assert client.get("/assets/nope.js").status_code == 404
