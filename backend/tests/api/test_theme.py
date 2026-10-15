"""Erscheinungsbild: the theme of the guest UI and the Live Wall
(`/api/theme`, `/api/theme.css`, `/api/admin/theme`)."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.extensions.wall.config import CONFIG_KEY, load_config
from virtubooth.extensions.wall.feed import config_payload, wall_screen_config
from virtubooth.services.theme import (
    KLASSISCH,
    NEON_NACHT,
    THEME_KEY,
    contrast,
    css_variables,
    ink_of,
    readable_on,
)

from ..conftest import ORIGIN


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


def colors(**changes: str) -> dict[str, str]:
    return NEON_NACHT.model_dump() | changes


def test_public_default_is_neon_nacht(client):
    r = client.get("/api/theme")
    assert r.status_code == 200
    body = r.json()
    assert body["preset"] == "neon_nacht"
    assert body["colors"] == NEON_NACHT.model_dump()
    assert body["rev"] == 0
    # no admin details in the public answer
    assert "by" not in body and "updated_at" not in body
    # black reads best on electric violet (4.5:1); white does not
    assert body["on_primary"] == "#000000"
    assert r.headers["etag"]
    assert "no-cache" in r.headers["cache-control"]


def test_public_etag_and_304(client, admin):
    first = client.get("/api/theme")
    etag = first.headers["etag"]
    again = client.get("/api/theme", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert admin.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN).is_success
    changed = client.get("/api/theme", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag
    assert changed.json()["colors"] == KLASSISCH.model_dump()


def test_css(client):
    r = client.get("/api/theme.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "--t-background:#1b1b1a" in r.text
    assert "--t-text-muted:#bdb3c4" in r.text
    assert "--t-on-primary:#000000" in r.text
    assert (
        client.get("/api/theme.css", headers={"If-None-Match": r.headers["etag"]}).status_code
        == 304
    )


def test_admin_requires_login(client):
    assert client.get("/api/admin/theme").status_code == 401
    r = client.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN)
    assert r.status_code == 401


def test_admin_get_lists_presets(admin):
    r = admin.get("/api/admin/theme")
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body["presets"]] == ["neon_nacht", "klassisch"]
    assert [p["label"] for p in body["presets"]] == ["Neon Nacht", "Klassisch"]
    assert body["theme"]["custom"] is False
    assert body["theme"]["by"] is None


def test_save_preset_audits_and_announces(admin, core, published):
    r = admin.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    theme = r.json()["theme"]
    assert theme["preset"] == "klassisch"
    assert theme["colors"] == KLASSISCH.model_dump()
    assert theme["rev"] == 1
    assert theme["custom"] is True
    assert theme["by"].startswith("admin")
    assert theme["on_primary"] == "#2b0f0c"  # today's ink on the safelight button
    stored = core.repos.app_settings.get(THEME_KEY)
    assert stored["preset"] == "klassisch" and stored["rev"] == 1
    assert ("theme.changed", {}) in published
    row = core.db.one("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1")
    assert row["action"] == "settings.theme"


def test_save_custom_colours_lower_cases(admin):
    body = {"preset": "custom", "colors": colors(primary="#22C55E")}
    r = admin.put("/api/admin/theme", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["theme"]["colors"]["primary"] == "#22c55e"
    assert r.json()["theme"]["preset"] == "custom"


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"primary": "#abc"}, "colors.primary"),
        ({"accent": "red"}, "colors.accent"),
        ({"hit": "#b6ff3cff"}, "colors.hit"),
    ],
)
def test_invalid_colour_names_the_field(admin, changes, field):
    r = admin.put(
        "/api/admin/theme", json={"preset": "custom", "colors": colors(**changes)}, headers=ORIGIN
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_theme"
    assert r.json()["field"] == field


def test_missing_and_unknown_colours(admin):
    partial = colors()
    del partial["depth"]
    r = admin.put("/api/admin/theme", json={"preset": "custom", "colors": partial}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["field"] == "colors.depth"
    r = admin.put(
        "/api/admin/theme",
        json={"preset": "custom", "colors": colors(sparkle="#ffffff")},
        headers=ORIGIN,
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_theme"
    r = admin.put("/api/admin/theme", json={"preset": "custom"}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["field"] == "colors"


@pytest.mark.parametrize(
    ("changes", "pair", "words"),
    [
        ({"text": "#4a4a4a"}, "colors.text/background", "Text auf Hintergrund"),
        ({"surface": "#c0c0c0", "text": "#ffffff"}, "colors.text/surface", "Text auf Fläche"),
        ({"text_muted": "#555555"}, "colors.text_muted/background", "Nebentext auf Hintergrund"),
    ],
)
def test_contrast_is_checked(admin, core, changes, pair, words):
    r = admin.put(
        "/api/admin/theme", json={"preset": "custom", "colors": colors(**changes)}, headers=ORIGIN
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid_theme"
    assert body["field"] == pair
    assert words in body["message"] and "4,5:1" in body["message"]
    assert core.repos.app_settings.get(THEME_KEY) == {}


def test_reset(admin, core, published):
    admin.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN)
    published.clear()
    r = admin.delete("/api/admin/theme", headers=ORIGIN)
    assert r.status_code == 200
    assert r.json()["theme"]["preset"] == "neon_nacht"
    assert r.json()["theme"]["custom"] is False
    assert core.repos.app_settings.get(THEME_KEY) == {}
    assert ("theme.changed", {}) in published
    # a second reset changes nothing
    published.clear()
    assert admin.delete("/api/admin/theme", headers=ORIGIN).status_code == 200
    assert published == []


def test_needs_origin(admin):
    r = admin.put("/api/admin/theme", json={"preset": "klassisch"})
    assert r.status_code == 403


def test_stored_garbage_falls_back(client, core):
    core.repos.app_settings.put(THEME_KEY, {"preset": "x", "colors": {"primary": 1}}, at="now")
    assert client.get("/api/theme").json()["colors"] == NEON_NACHT.model_dump()


def test_readable_on_and_css_variables():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert readable_on("#ffffff", NEON_NACHT) == NEON_NACHT.background
    assert readable_on(NEON_NACHT.primary, NEON_NACHT) == "#000000"


# -------------------------------------------------------------- the wall


def test_wall_follows_theme_unless_set(admin, core):
    config = load_config(core.repos.app_settings)
    assert config.look.primary is None
    look = wall_screen_config(core, config).look
    assert (look.primary, look.secondary, look.background) == (
        NEON_NACHT.primary,
        NEON_NACHT.accent,
        NEON_NACHT.background,
    )
    admin.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN)
    payload = config_payload(core, config)
    assert payload["config"]["look"]["primary"] == KLASSISCH.primary
    assert payload["theme"]["preset"] == "klassisch"
    explicit = config.model_copy(
        update={"look": config.look.model_copy(update={"primary": "#123456"})}
    )
    assert wall_screen_config(core, explicit).look.primary == "#123456"


def test_wall_legacy_default_colours_follow_theme(core):
    core.repos.app_settings.put(
        CONFIG_KEY,
        {"look": {"preset": "aurora", "primary": "#a855f7", "secondary": "#00ff00"}},
        at="now",
    )
    look = load_config(core.repos.app_settings).look
    assert look.preset == "aurora"
    assert look.primary is None
    assert look.secondary == "#00ff00"


def test_css_variables_shape():
    from virtubooth.api.schemas.theme import PublicTheme

    css = css_variables(
        PublicTheme(
            preset="klassisch",
            colors=KLASSISCH,
            on_primary="#2b0f0c",
            on_accent="#2b0f0c",
            primary_ink="#ffa630",
            rev=3,
        )
    )
    assert css.startswith(":root{--t-background:#2b0f0c;")
    assert css.count("--t-") == 14


def test_primary_ink():
    # electric violet is 4.1:1 on charcoal: lightened just enough; amber reads as is
    ink = ink_of(NEON_NACHT.primary, NEON_NACHT)
    assert ink != NEON_NACHT.primary
    assert contrast(ink, NEON_NACHT.background) >= 4.5
    assert contrast(ink, NEON_NACHT.surface) >= 4.5
    assert ink_of(KLASSISCH.primary, KLASSISCH) == KLASSISCH.primary


# -------------------------------------------------------- the pages' <head>


def test_guest_pages_link_the_theme_admin_does_not(client, admin):
    from ..conftest import scan

    gate = client.get("/")
    assert gate.status_code == 404
    assert '<link rel="stylesheet" href="/api/theme.css?v=' in gate.text
    scan(client)
    page = client.get("/")
    link = page.text.split('href="/api/theme.css?v=')[1].split('"')[0]
    assert page.status_code == 200 and link
    assert "/api/theme.css" not in admin.get("/admin/live").text
    # a new theme: a new link (and a new ETag for the page)
    etag = page.headers["etag"]
    admin.put("/api/admin/theme", json={"preset": "klassisch"}, headers=ORIGIN)
    again = client.get("/")
    assert again.headers["etag"] != etag
    assert f"theme.css?v={link}" not in again.text
