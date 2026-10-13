"""Live-Wall admin: the manage section `?tab=livewall` and the inspector's Analyse panel.

The wall backend (PLAN-WALL §4.3/§4.4) is built elsewhere, so `page.route` serves a
stateful fake of `/api/x/wall/admin/**`, and the extension list gets a loaded `wall`.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route, expect

from ..conftest import LiveServer
from .conftest import Guest, errors, goto, no_horizontal_scroll, toast

pytestmark = pytest.mark.e2e

PREFIX = "/api/x/wall/admin"

WALL_EXTENSION = {
    "id": "wall",
    "title": "Live-Wall",
    "emoji": "📺",
    "tagline": "",
    "url": None,
    "uploads": False,
    "meta_labels": {},
    "loaded": True,
}

DEFAULTS: dict[str, Any] = {
    "rev": 0,
    "updated_at": None,
    "by": None,
    "playlist": [
        {"mode": "spotlight", "enabled": True, "duration_s": 120},
        {"mode": "gallery", "enabled": True, "duration_s": 45},
        {"mode": "categories", "enabled": True, "duration_s": 60},
    ],
    "spotlight": {
        "algorithm": "fresh_first",
        "n": 12,
        "interval_s": 8,
        "transition": "random",
        "transition_ms": 1200,
    },
    "gallery": {"speed": "medium", "rows": 3},
    "categories": {"per_category_s": 10, "disabled": []},
    "sources": [],
    "delay_s": 20,
    "show_instagram": False,
    "look": {
        "preset": "blobs",
        "primary": "#a855f7",
        "secondary": "#ff4fa3",
        "background": "#2b2b31",
        "fps": 30,
        "calm": False,
    },
    "overlay": {"event_name": True, "counter": True, "qr": False, "corner": "bottom-right"},
}

CATEGORIES = [
    ("volles_haus", "👥", "Volles Haus", "Die meisten Leute auf einem Foto", True, None),
    ("grinsekatzen", "😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild", False,
     "Braucht die Gesichtserkennung (KI)."),
    ("eroeffnung", "🎬", "Eröffnungsfoto", "Das allererste Foto des Abends", True, None),
]  # fmt: skip


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class FakeWall:
    """The wall's admin API as a dict in memory; records every request."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.password: dict[str, Any] = {"set": False, "changed_at": None}
        self.disabled_analyzers: list[str] = []
        self.analysis: dict[str, dict[str, Any]] = {}
        self.winner: str | None = None
        self.requests: list[tuple[str, str, Any]] = []

    def sent(self, method: str, path: str) -> list[Any]:
        return [b for m, p, b in self.requests if m == method and p == path]

    def categories(self, winners: bool) -> list[dict[str, Any]]:
        out = []
        for cid, emoji, title, line, available, reason in CATEGORIES:
            cat: dict[str, Any] = {
                "id": cid,
                "emoji": emoji,
                "title": title,
                "line": line,
                "enabled": cid not in self.config["categories"]["disabled"],
                "available": available,
                "reason": reason,
            }
            if winners:
                cat["winners"] = (
                    [{"photo_id": self.winner, "thumb_url": f"/media/{self.winner}?thumb=1",
                      "value": 1, "label": "um 19:42"}]
                    if self.winner and cid == "eroeffnung" else []
                )  # fmt: skip
            out.append(cat)
        return out

    def admin_out(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "defaults": DEFAULTS,
            "password": self.password,
            "wall_path": "/livewall",
            "sources": [{"id": "beer", "title": "Bier", "emoji": "🍺"}],
            "categories": self.categories(winners=False),
            "open_walls": 2,
            "event_name": "Testparty",
        }

    def status(self) -> dict[str, Any]:
        analyzers = [
            ("basic", "Helligkeit und Farben", "basic", True, None),
            ("faces", "Gesichter", "ml", True, None),
            ("age", "Alter schätzen", "ml", True, None),
        ]
        return {
            "worker": {"state": "running", "ml": True, "message": None, "last_beat_at": now()},
            "counts": {"pending": 2, "running": 1, "done": 12, "failed": 1, "skipped": 0,
                       "total": 16},
            "analyzers": [
                {"name": n, "title": t, "kind": k, "version": "1",
                 "enabled": n not in self.disabled_analyzers, "available": a, "reason": r,
                 "facts": []}
                for n, t, k, a, r in analyzers
            ],
        }  # fmt: skip

    def photo_analysis(self, photo_id: str, state: str = "done") -> dict[str, Any]:
        return {
            "photo_id": photo_id,
            "state": state,
            "attempts": 1,
            "error": None,
            "finished_at": now() if state == "done" else None,
            "versions": {"basic": 1, "faces": 1},
            "facts": {"faces": 2, "people": 2, "smiles": 1, "brightness": 0.4321},
            "boxes": [
                {"kind": "face", "x": 0.2, "y": 0.18, "w": 0.22, "h": 0.17, "label": "Gesicht",
                 "score": 0.93},
                {"kind": "face", "x": 0.55, "y": 0.25, "w": 0.2, "h": 0.16, "label": "Gesicht",
                 "score": 0.88},
                {"kind": "hand", "x": 0.62, "y": 0.6, "w": 0.15, "h": 0.12, "label": "Peace",
                 "score": 0.7},
            ],
            "details": [{"label": "Personen", "value": "2"}, {"label": "Lächeln", "value": "1"}],
        }  # fmt: skip

    def handle(self, route: Route) -> None:
        req = route.request
        path = urlparse(req.url).path.removeprefix(PREFIX)
        body = req.post_data_json if req.post_data else None
        self.requests.append((req.method, path, body))
        status, answer = self.answer(req.method, path, body)
        route.fulfill(status=status, json=answer)

    def answer(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        match method, path:
            case "GET", "/config":
                return 200, self.admin_out()
            case "PUT", "/config":
                self.config = {**body, "rev": self.config["rev"] + 1, "updated_at": now(),
                               "by": "admin:1"}  # fmt: skip
                return 200, self.admin_out()
            case "PUT", "/password":
                if len(body["password"]) < 6:
                    return 400, {"error": "wall_password_too_short",
                                 "message": "Mindestens 6 Zeichen."}  # fmt: skip
                self.password = {"set": True, "changed_at": now()}
                return 200, self.password
            case "DELETE", "/password":
                self.password = {"set": False, "changed_at": None}
                return 200, self.password
            case "POST", "/logout":
                return 200, {"ok": True}
            case "GET", "/categories":
                return 200, {"categories": self.categories(winners=True)}
            case "GET", "/analysis":
                return 200, self.status()
            case "PUT", "/analysis/analyzers":
                self.disabled_analyzers = list(body["disabled"])
                return 200, self.status()
            case "POST", "/analysis/rerun":
                return 200, {"queued": 1 if body["scope"] == "failed" else 16}
        m = re.fullmatch(r"/photos/([^/]+)/analysis", path)
        if m and method == "GET":
            return 200, self.analysis.setdefault(m[1], self.photo_analysis(m[1]))
        if m and method == "POST":
            self.analysis[m[1]] = self.photo_analysis(m[1], "pending")
            return 200, self.analysis[m[1]]
        return 404, {"error": "http_404", "message": "Not Found"}


def install(page: Page) -> FakeWall:
    fake = FakeWall()

    def extensions(route: Route) -> None:
        response = route.fetch()
        data = response.json()
        data["extensions"].append(WALL_EXTENSION)
        route.fulfill(response=response, json=data)

    page.route("**/api/admin/extensions", extensions)
    page.route(f"**{PREFIX}/**", fake.handle)
    return fake


@pytest.fixture
def wall(desktop_page: Page) -> Iterator[FakeWall]:
    yield install(desktop_page)


def pick(page: Page, testid: str, option: str) -> None:
    page.get_by_test_id(testid).get_by_role("button").click()
    page.get_by_role("option", name=option, exact=True).click()


def test_nav_opens_the_section(desktop_page: Page, live: LiveServer, wall: FakeWall) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage")
    page.get_by_role("navigation", name="Verwaltung").get_by_role(
        "link", name=re.compile("^Live-Wall")
    ).click()
    page.wait_for_url(live.url("/admin/manage?tab=livewall"))
    expect(page.get_by_role("heading", name="Live-Wall", level=1)).to_be_focused()
    expect(page.get_by_test_id("wall-open-count")).to_have_text("2 Wände offen")
    expect(page.get_by_test_id("wall-open")).to_have_attribute("href", "/livewall")
    expect(page.get_by_test_id("wall-open")).to_have_attribute("target", "_blank")
    for title in ["Zugang", "Ablauf", "Einzelbild", "Galerie", "Fotos", "Aussehen",
                  "Einblendungen", "Kategorien", "Analyse"]:  # fmt: skip
        expect(page.get_by_role("heading", name=title, level=2, exact=True)).to_be_visible()
    expect(page.get_by_test_id("wall-counts")).to_have_text(
        "12 fertig · 3 warten · 1 fehlgeschlagen"
    )
    cats = page.get_by_test_id("wall-categories")
    expect(cats.locator("[data-category=grinsekatzen]")).to_contain_text("Braucht Analyse")
    expect(cats.locator("[data-category=volles_haus]")).to_contain_text("Noch kein Foto")
    expect(page.get_by_test_id("wall-savebar")).to_have_count(0)
    assert no_horizontal_scroll(page)
    assert errors(page) == []


def test_change_transition_and_colour_then_save(
    desktop_page: Page, live: LiveServer, wall: FakeWall
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=livewall")
    pick(page, "wall-transition", "Glitch")
    primary = page.get_by_role("textbox", name="Hauptfarbe", exact=True)
    primary.fill("#112233")
    grinsen = page.get_by_role("switch", name="Grinsekatzen zeigen")
    page.locator("[data-category=grinsekatzen]").get_by_text("Zeigen", exact=True).click()
    expect(grinsen).not_to_be_checked()
    expect(page.get_by_test_id("wall-savebar")).to_be_visible()

    # an out-of-range value blocks saving and says why
    interval = page.get_by_role("textbox", name="Wechsel alle (Sekunden)")
    interval.fill("1")
    page.get_by_test_id("wall-save").click()
    expect(page.get_by_test_id("wall-savebar")).to_contain_text("Bitte die markierten Felder")
    expect(page.get_by_text("Bitte eine ganze Zahl von 3 bis 120.")).to_be_visible()
    assert wall.sent("PUT", "/config") == []
    interval.fill("10")

    page.get_by_test_id("wall-save").click()
    expect(toast(page)).to_contain_text("Gespeichert. Offene Wände übernehmen es sofort.")
    expect(page.get_by_test_id("wall-savebar")).to_have_count(0)
    (body,) = wall.sent("PUT", "/config")
    assert body["spotlight"]["transition"] == "glitch"
    assert body["spotlight"]["interval_s"] == 10
    assert body["look"]["primary"] == "#112233"
    assert body["categories"]["disabled"] == ["grinsekatzen"]
    assert body["playlist"] == DEFAULTS["playlist"]
    assert "rev" not in body and "by" not in body
    # the saved state is the new base: the field keeps the value, nothing is dirty
    expect(primary).to_have_value("#112233")

    # Verwerfen goes back to the saved state
    pick(page, "wall-preset", "Disco-Gitter")
    page.get_by_test_id("wall-discard").click()
    expect(page.get_by_test_id("wall-preset").get_by_role("button")).to_contain_text("Farbblasen")
    assert len(wall.sent("PUT", "/config")) == 1
    assert errors(page) == []


def test_set_password_and_log_out_walls(
    desktop_page: Page, live: LiveServer, wall: FakeWall
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=livewall")
    status = page.get_by_test_id("wall-password-status")
    expect(status).to_have_text("Noch kein Passwort: die Live-Wall ist gesperrt.")
    field = page.get_by_label("Live-Wall-Passwort")
    field.fill("kurz")
    page.get_by_test_id("wall-password-submit").click()
    expect(page.get_by_text("Das Passwort ist zu kurz: mindestens 6 Zeichen.")).to_be_visible()
    assert wall.sent("PUT", "/password") == []

    field.fill("geheim123")
    page.get_by_test_id("wall-password-submit").click()
    expect(status).to_have_text(re.compile(r"^Passwort gesetzt am .+\.$"))
    assert wall.sent("PUT", "/password") == [{"password": "geheim123"}]
    expect(page.get_by_test_id("wall-password-submit")).to_have_text("Passwort ändern")
    expect(field).to_have_value("")

    page.get_by_test_id("wall-logout").click()
    expect(toast(page)).to_contain_text("Alle Wände sind abgemeldet.")
    assert wall.sent("POST", "/logout") == [None]

    page.get_by_test_id("wall-password-clear").click()
    dialog = page.get_by_test_id("confirm").get_by_role("alertdialog")
    expect(dialog).to_contain_text("Alle offenen Wände werden abgemeldet.")
    dialog.get_by_role("button", name="Passwort entfernen").click()
    expect(status).to_have_text("Noch kein Passwort: die Live-Wall ist gesperrt.")
    assert len(wall.sent("DELETE", "/password")) == 1
    assert errors(page) == []


def test_inspector_shows_the_analysis(
    desktop_page: Page, live: LiveServer, wall: FakeWall, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    photo = guests().upload()
    goto(page, live, f"/admin/manage?photo={photo}")
    panel = page.get_by_test_id("inspector").get_by_test_id("analysis")
    expect(panel.get_by_role("heading", name="Analyse")).to_be_visible()
    expect(panel.get_by_test_id("analysis-state")).to_have_text("fertig")
    boxes = panel.get_by_test_id("analysis-box")
    expect(boxes).to_have_count(3)
    assert boxes.first.evaluate("(el) => parseFloat(el.style.left)") == 20
    expect(panel.get_by_test_id("analysis-details")).to_contain_text("Personen")
    panel.get_by_text("Rahmen zeigen").click()
    expect(boxes).to_have_count(0)

    panel.get_by_role("button", name="Neu analysieren").click()
    expect(panel.get_by_test_id("analysis-state")).to_have_text("wartet")
    assert wall.sent("POST", f"/photos/{photo}/analysis") == [None]
    assert errors(page) == []


def test_without_the_wall_extension_the_inspector_has_no_panel(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    photo = guests().upload()
    goto(page, live, f"/admin/manage?photo={photo}")
    expect(
        page.get_by_test_id("inspector").get_by_role("heading", name="Bier 0001")
    ).to_be_visible()
    expect(page.get_by_test_id("analysis")).to_have_count(0)
    goto(page, live, "/admin/manage?tab=livewall")
    expect(page.get_by_text("Die Live-Wall ist auf diesem Server aus.")).to_be_visible()
    assert errors(page) == []


def test_section_on_a_phone(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    install(page)
    goto(page, live, "/admin/manage?tab=livewall")
    expect(page.get_by_test_id("wall-counts")).to_be_visible()
    page.get_by_role("textbox", name="Reihen").fill("4")
    expect(page.get_by_test_id("wall-save")).to_be_in_viewport()
    assert no_horizontal_scroll(page)
    assert errors(page) == []
