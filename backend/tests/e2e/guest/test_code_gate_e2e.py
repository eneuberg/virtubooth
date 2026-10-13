"""A guest comes in through QR code 2 and joins; the admin sees the guest at that code.
Once the host deletes code 2, its link only shows the gate, while the guest who joined
through it stays on the party."""

from __future__ import annotations

from typing import Any

import httpx2 as httpx
import pytest
from playwright.sync_api import Page, expect

from ...conftest import ADMIN_PASSWORD
from ..conftest import LiveServer, accept_consent_in_browser
from .conftest import reload

pytestmark = pytest.mark.e2e

TOKEN_2 = "second-qr-code-token-0002"


def admin_client(live: LiveServer) -> httpx.Client:
    client = httpx.Client(base_url=live.base_url, headers={"Origin": live.base_url})
    r = client.post("/api/admin/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return client


def code_2(admin: httpx.Client) -> dict[str, Any]:
    r = admin.get("/api/admin/codes")
    assert r.status_code == 200, r.text
    found: dict[str, Any] = next(c for c in r.json()["codes"] if c["id"] == 2)
    return found


def test_a_guest_of_a_deleted_code_stays(make_page: Any, live: LiveServer) -> None:
    live.core.services.codes.create(token=TOKEN_2, target="", note="Eingang", actor="pytest")
    url = live.url(f"/?t={TOKEN_2}")
    admin = admin_client(live)
    try:
        guest: Page = make_page("phone")
        guest.goto(url)
        accept_consent_in_browser(guest)
        expect(guest.get_by_test_id("start")).to_be_visible()
        stats = code_2(admin)["stats"]
        assert (stats["guests"], stats["scans"], stats["people"]) == (1, 1, 1)

        r = admin.delete("/api/admin/codes/2")
        assert r.status_code == 200 and r.json()["code"]["active"] is False

        stranger: Page = make_page("phone")
        response = stranger.goto(url)
        assert response is not None and response.status == 404
        expect(stranger.get_by_test_id("gate")).to_be_visible()
        assert not any(c["name"] == "vb_access" for c in stranger.context.cookies())

        reload(guest)
        expect(guest.get_by_test_id("start")).to_be_visible()
        assert guest.js_errors == []  # type: ignore[attr-defined]
        assert code_2(admin)["stats"]["guests"] == 1
    finally:
        admin.close()
