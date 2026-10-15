"""Live-Wall admin: the manage section `?tab=livewall` (settings and the category
editor) and the inspector's Analyse panel.

The wall backend (PLAN-WALL §4.3/§4.4, PLAN-NIGHT §4.3) is built elsewhere, so
`page.route` serves a stateful fake of `/api/x/wall/admin/**`, and the extension list
gets a loaded `wall`. test_ml_pipeline_e2e.py reuses the fake.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Locator, Page, Route, expect

from virtubooth.extensions.sdk import discover_extensions

from ..conftest import LiveServer, shot
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


def spec(
    emoji: str,
    title: str,
    line: str,
    where: list[dict[str, Any]],
    by: str,
    *,
    count: int = 3,
    order: str = "top",
    style: str = "count",
    one: str = "",
    many: str = "",
    verdict: str | None = None,
) -> dict[str, Any]:
    return {
        "emoji": emoji,
        "title": title,
        "line": line,
        "where": where,
        "select": {"by": by, "order": order, "count": count, "then_by": [],
                   "one_per_guest": False},
        "label": {"value": None, "style": style, "one": one, "many": many},
        "verdict": {"prompt": verdict} if verdict else None,
    }  # fmt: skip


PRESETS: dict[str, dict[str, Any]] = {
    "volles_haus": spec("👥", "Volles Haus", "Die meisten Leute auf einem Foto",
                        [{"value": "people", "op": "gte", "operand": 3}], "people",
                        one="Person", many="Personen"),
    "grinsekatzen": spec("😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild",
                         [{"value": "smiles", "op": "gte", "operand": 2}], "smiles",
                         one="Lächeln", many="Lächeln"),
    "eroeffnung": spec("🎬", "Eröffnungsfoto", "Das allererste Foto des Abends", [],
                       "photo.created_at", count=1, order="bottom", style="time"),
}  # fmt: skip
UNAVAILABLE = {"grinsekatzen": "Braucht die Gesichtserkennung (KI)."}

VALUES = {
    "values": [
        {"key": k, "title": t, "group": g, "kind": kind, "unit": None, "needs": None,
         "available": True, "reason": None, "archived": False}
        for k, t, g, kind in [
            ("people", "Personen", "Gesichter und Personen", "count"),
            ("smiles", "Lächeln", "Gesichter und Personen", "count"),
            ("colorfulness", "Farbigkeit", "Bild", "number"),
            ("objects", "Objekte (Liste)", "Objekte", "labels"),
            ("objects.count", "Anzahl Objekte", "Objekte", "count"),
            ("prop.coolness.max", "coolness (höchster)", "Eigenschaften", "number"),
            ("photo.created_at", "Aufnahmezeit", "Foto", "time"),
        ]
    ],
    "labels": [
        {"label": "hat", "label_de": "Hut", "count": 3},
        {"label": "wine glass", "label_de": "Weinglas", "count": 14},
    ],
}  # fmt: skip


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class FakeWall:
    """The wall's admin API as a dict in memory; records every request."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.password: dict[str, Any] = {"set": False, "changed_at": None}
        self.disabled_analyzers: list[str] = []
        self.settings: dict[str, float] = {"score_min": 0.35, "max_objects": 50}
        self.analysis: dict[str, dict[str, Any]] = {}
        self.winners: list[str] = []  # photo ids leading "eroeffnung", best first
        self.worker: dict[str, Any] = {}  # extra heartbeat fields of the worker
        self.requests: list[tuple[str, str, Any]] = []
        self.open_walls = 2
        self.cats: list[dict[str, Any]] = [
            {"id": cid, "enabled": True, "preset": cid, "spec": copy.deepcopy(s)}
            for cid, s in PRESETS.items()
        ]

    def sent(self, method: str, path: str) -> list[Any]:
        return [b for m, p, b in self.requests if m == method and p == path]

    def item(self, cat: dict[str, Any]) -> dict[str, Any]:
        cid = cat["id"]
        winners = (
            [{"photo_id": w, "thumb_url": f"/media/{w}?thumb=1", "value": i + 1,
              "label": f"um 19:4{i}", "object_idx": None}
             for i, w in enumerate(self.winners[: cat["spec"]["select"]["count"]])]
            if cid == "eroeffnung" else []
        )  # fmt: skip
        return {
            **cat,
            "position": self.cats.index(cat),
            "available": cid not in UNAVAILABLE,
            "reason": UNAVAILABLE.get(cid),
            "verdict": None,
            "winners": winners,
        }

    def items(self) -> list[dict[str, Any]]:
        return [self.item(c) for c in self.cats]

    def find(self, cid: str) -> dict[str, Any] | None:
        return next((c for c in self.cats if c["id"] == cid), None)

    def admin_out(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "defaults": DEFAULTS,
            "password": self.password,
            "wall_path": "/livewall",
            "sources": [{"id": "beer", "title": "Bier", "emoji": "🍺"}],
            "categories": [
                {
                    "id": c["id"],
                    "emoji": c["spec"]["emoji"],
                    "title": c["spec"]["title"],
                    "line": c["spec"]["line"],
                    "enabled": c["enabled"],
                    "available": c["id"] not in UNAVAILABLE,
                    "reason": UNAVAILABLE.get(c["id"]),
                }
                for c in self.cats
            ],
            "open_walls": self.open_walls,
            "event_name": "Testparty",
        }

    def status(self) -> dict[str, Any]:
        analyzers = [
            ("basic", "Helligkeit und Farben", "basic", True, None, None),
            ("faces", "Gesichter", "ml", True, None, 3.4),
            ("objects", "Objekte", "ml", True, None, 12),
            ("age", "Alter schätzen", "ml", True, None, 87),
        ]
        return {
            "worker": {"state": "running", "ml": True, "message": None, "last_beat_at": now(),
                       "processed": None, "rss_mb": None, "load_errors": {}, **self.worker},
            "counts": {"pending": 2, "running": 1, "done": 12, "failed": 1, "skipped": 0,
                       "total": 16},
            "queue": {"pending": 3, "running": 1, "oldest_pending_s": 12},
            "analyzers": [
                {"name": n, "title": t, "kind": k, "version": "1",
                 "enabled": n not in self.disabled_analyzers, "available": a, "reason": r,
                 "facts": [], "description": f"{t}: was es tut.", "size_mb": size,
                 "stats": {"processed": 128, "errors": 2, "avg_ms": 340, "last_ms": 290},
                 "settings": dict(self.settings) if n == "objects" else None,
                 "settings_schema": [
                     {"key": "score_min", "title": "Mindest-Sicherheit", "min": 0.05,
                      "max": 0.95, "step": 0.05},
                     {"key": "max_objects", "title": "Höchstens Objekte", "min": 1,
                      "max": 100, "step": 1},
                 ] if n == "objects" else []}
                for n, t, k, a, r, size in analyzers
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
            "objects": [
                {"idx": 0, "label": "wine glass", "label_de": "Weinglas", "score": 0.91,
                 "box": {"x": 0.3, "y": 0.5, "w": 0.1, "h": 0.2}, "source": "local",
                 "model": "objects@1"},
                {"idx": 1, "label": "hat", "label_de": "Hut", "score": 0.8, "box": None,
                 "source": "claude", "model": "claude-haiku-5-5"},
            ],
            "runs": [
                {"source": "local", "state": "done", "model": "objects@1", "error": None},
                {"source": "claude", "state": "done", "model": "claude-haiku-5-5",
                 "error": None},
            ],
            "opt_out": {"analysis": False, "external_ai": True},
            "properties": [{"name": "coolness", "archived": False, "scores": [0.2, 0.9]}],
            "durations_ms": {"basic": 12, "faces": 140},
        }  # fmt: skip

    def handle(self, route: Route) -> None:
        req = route.request
        path = urlparse(req.url).path.removeprefix(PREFIX)
        json_body = "application/json" in (req.headers.get("content-type") or "")
        body = req.post_data_json if json_body and req.post_data_buffer else None
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
                return 200, {"categories": self.items()}
            case "POST", "/categories":
                if self.find(body["id"]):
                    return 409, {"error": "category_exists", "message": "Gibt es schon."}
                if body["spec"]["title"] == "Fehler":
                    return 400, {"error": "invalid_category",
                                 "message": "Titel: Dieser Titel geht nicht."}  # fmt: skip
                cat = {"id": body["id"], "enabled": body.get("enabled", True), "preset": None,
                       "spec": body["spec"]}  # fmt: skip
                self.cats.append(cat)
                return 201, self.item(cat)
            case "PUT", "/categories/order":
                order = {cid: i for i, cid in enumerate(body["ids"])}
                self.cats.sort(key=lambda c: order[c["id"]])
                return 200, {"categories": self.items()}
            case "POST", "/categories/restore-presets":
                added = [cid for cid in PRESETS if not self.find(cid)]
                self.cats += [{"id": cid, "enabled": True, "preset": cid,
                               "spec": copy.deepcopy(PRESETS[cid])} for cid in added]  # fmt: skip
                return 200, {"added": added}
            case "POST", "/categories/preview":
                winners = [{"photo_id": w, "thumb_url": f"/media/{w}?thumb=1", "value": 7,
                            "label": "7 Personen", "object_idx": None}
                           for w in self.winners[: body["spec"]["select"]["count"]]]  # fmt: skip
                return 200, {"winners": winners, "matched": 5, "reason": None}
            case "GET", "/values":
                return 200, VALUES
            case "GET", "/analysis":
                return 200, self.status()
        m = re.fullmatch(r"/categories/([a-z0-9_]+)", path)
        if m and (cat := self.find(m[1])):
            if method == "PUT":
                cat.update(spec=body["spec"], enabled=body["enabled"])
                return 200, self.item(cat)
            if method == "DELETE":
                self.cats.remove(cat)
                return 200, {"ok": True}
        m = re.fullmatch(r"/analysis/analyzers/([a-z_]+)", path)
        if m and method == "PUT":
            on = body["enabled"]
            self.disabled_analyzers = [n for n in self.disabled_analyzers if n != m[1]]
            if not on:
                self.disabled_analyzers.append(m[1])
            self.settings.update(body.get("settings") or {})
            return 200, self.status()
        m = re.fullmatch(r"/photos/([^/]+)/analysis", path)
        if m and method == "GET":
            return 200, self.analysis.setdefault(m[1], self.photo_analysis(m[1]))
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
                  "Einblendungen", "Kategorien"]:  # fmt: skip
        expect(page.get_by_role("heading", name=title, level=2, exact=True)).to_be_visible()
    # the analysis moved to the ML-Pipeline; no re-run anywhere
    expect(page.get_by_role("heading", name="Analyse", level=2, exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("neu analysieren", re.I))).to_have_count(0)
    cats = page.get_by_test_id("wall-categories")
    expect(cats.locator("[data-category=volles_haus]")).to_contain_text("Vorlage")
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
    # categories are switched in their own card now: the old list is not sent
    assert body["categories"] == {"per_category_s": DEFAULTS["categories"]["per_category_s"]}
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
    inspector = page.get_by_test_id("inspector")
    panel = inspector.get_by_test_id("analysis")
    expect(panel.get_by_role("heading", name="Analyse")).to_be_visible()
    expect(panel.get_by_test_id("analysis-state")).to_have_text("fertig")
    # the frames lie on the inspector's big photo, not on a second thumbnail
    boxes = inspector.get_by_test_id("analysis-box")
    # 2 faces, a hand and the wine glass (the hat from Claude has no box)
    expect(boxes).to_have_count(4)
    expect(panel.locator("img")).to_have_count(0)
    assert boxes.first.evaluate("(el) => parseFloat(el.style.left)") == 20
    photo_box = inspector.get_by_test_id("fitted-photo").bounding_box()
    img_box = inspector.get_by_role("img", name="Bier 0001").bounding_box()
    assert photo_box and img_box
    assert abs(photo_box["width"] - img_box["width"]) < 1.5
    assert abs(photo_box["height"] - img_box["height"]) < 1.5
    expect(panel.get_by_test_id("analysis-details")).to_contain_text("Personen")
    # the frozen object list: label, score, source, property scores, runs
    objects = panel.get_by_test_id("analysis-object")
    expect(objects).to_have_count(2)
    expect(objects.first).to_contain_text("Weinglas")
    expect(objects.first).to_contain_text("lokal")
    expect(objects.nth(1)).to_contain_text("Claude")
    expect(objects.nth(1)).to_contain_text("coolness 0,90")
    expect(panel.get_by_test_id("analysis-runs")).to_contain_text("Erkennung Claude: fertig")
    expect(panel.get_by_test_id("analysis-opt-out")).to_have_text("Keine externe KI")
    # hovering the wine glass lights its frame
    objects.first.hover()
    expect(inspector.locator("[data-testid=analysis-box][data-object='0']")).to_have_attribute(
        "data-lit", "true"
    )
    panel.get_by_text("Rahmen auf dem Foto zeigen").click()
    expect(boxes).to_have_count(0)
    # analyses are frozen: no re-run
    expect(panel.get_by_role("button", name=re.compile("analysieren", re.I))).to_have_count(0)
    assert [r for r in wall.requests if r[0] == "POST"] == []
    assert errors(page) == []


@pytest.mark.parametrize(
    "e2e_extensions", [discover_extensions(["beer", "booth"])], ids=["without-wall"]
)
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
    expect(page.get_by_test_id("wall-categories")).to_be_visible()
    page.get_by_role("textbox", name="Reihen").fill("4")
    expect(page.get_by_test_id("wall-save")).to_be_in_viewport()
    assert no_horizontal_scroll(page)
    assert errors(page) == []


def test_leaving_with_unsaved_changes_asks_first(
    desktop_page: Page, live: LiveServer, wall: FakeWall
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=livewall")
    unload_held = "() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; }"
    assert page.evaluate(unload_held) is False
    page.get_by_role("textbox", name="Reihen").fill("4")
    expect(page.get_by_test_id("wall-savebar")).to_be_visible()
    # a reload or closing the tab: the browser asks
    assert page.evaluate(unload_held) is True

    nav = page.get_by_role("navigation", name="Verwaltung")
    nav.get_by_role("link", name=re.compile("^Fotos")).click()
    dialog = page.get_by_test_id("wall-leave").get_by_role("alertdialog")
    expect(dialog).to_contain_text("noch nicht gespeichert")
    dialog.get_by_role("button", name="Hierbleiben").click()
    expect(dialog).to_have_count(0)
    assert "tab=livewall" in page.url
    expect(page.get_by_role("textbox", name="Reihen")).to_have_value("4")

    nav.get_by_role("link", name=re.compile("^Fotos")).click()
    dialog.get_by_role("button", name="Verwerfen").click()
    expect(page.get_by_role("heading", name="Fotos", level=1)).to_be_visible()
    assert "livewall" not in page.url
    assert page.evaluate(unload_held) is False
    assert wall.sent("PUT", "/config") == []

    # saved changes leave without a question
    goto(page, live, "/admin/manage?tab=livewall")
    page.get_by_role("textbox", name="Reihen").fill("5")
    page.get_by_test_id("wall-save").click()
    expect(page.get_by_test_id("wall-savebar")).to_have_count(0)
    nav.get_by_role("link", name=re.compile("^Fotos")).click()
    expect(page.get_by_role("heading", name="Fotos", level=1)).to_be_visible()
    assert "livewall" not in page.url
    assert errors(page) == []


def test_winners_and_open_walls(
    desktop_page: Page, live: LiveServer, wall: FakeWall, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    wall.winners = [g.upload() for _ in range(4)]
    wall.cats[2]["spec"]["select"]["count"] = 3
    page.clock.install()
    goto(page, live, "/admin/manage?tab=livewall")

    # the leaders of a category, best first
    podium = page.locator("[data-category=eroeffnung]").get_by_test_id("wall-category-winners")
    expect(podium.get_by_role("img")).to_have_count(3)
    expect(podium.get_by_role("img").first).to_have_accessible_name("Platz 1: um 19:40")
    expect(page.locator("[data-category=volles_haus]")).to_contain_text("Noch kein Foto")

    # the open-walls count follows without a reload
    count = page.get_by_test_id("wall-open-count")
    expect(count).to_have_text("2 Wände offen")
    asked = len(wall.sent("GET", "/config"))
    wall.open_walls = 1
    page.clock.run_for(16_000)
    expect(count).to_have_text("1 Wand offen")
    assert len(wall.sent("GET", "/config")) > asked
    assert errors(page) == []


def test_phone_viewer_has_the_analysis(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = admin_page
    install(page)
    photo = guests().upload()
    goto(page, live, f"/admin/manage?photo={photo}")
    viewer = page.get_by_test_id("lightbox")
    expect(viewer).to_be_visible()
    panel = viewer.get_by_test_id("analysis")
    expect(panel.get_by_test_id("analysis-state")).to_have_text("fertig")
    boxes = viewer.get_by_test_id("analysis-box")
    expect(boxes).to_have_count(4)
    # on the photo itself
    photo_box = viewer.get_by_test_id("fitted-photo").bounding_box()
    first = boxes.first.bounding_box()
    assert photo_box and first
    assert abs(first["x"] - (photo_box["x"] + 0.2 * photo_box["width"])) < 2
    panel.get_by_text("Rahmen auf dem Foto zeigen").click()
    expect(boxes).to_have_count(0)
    assert no_horizontal_scroll(page)
    assert errors(page) == []


# ------------------------------------------------------------- category editor


def sheet(page: Page) -> Locator:
    return page.get_by_test_id("category-sheet").get_by_role("dialog")


def pick_value(scope: Locator, testid: str, option: str) -> None:
    scope.get_by_test_id(testid).get_by_role("button").click()
    scope.page.get_by_role("option", name=option, exact=True).click()


def test_create_a_category_with_preview(
    desktop_page: Page, live: LiveServer, wall: FakeWall, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    wall.winners = [g.upload() for _ in range(2)]
    goto(page, live, "/admin/manage?tab=livewall")
    page.get_by_test_id("category-new").click()
    dlg = sheet(page)
    expect(dlg.get_by_role("heading", name="Neue Kategorie")).to_be_visible()
    dlg.get_by_role("textbox", name="Titel", exact=True).fill("Hutträger")
    expect(dlg.get_by_role("textbox", name="Kennung")).to_have_value("huttraeger")
    dlg.get_by_role("textbox", name="Emoji").fill("🎩")
    # a condition on the object list: „enthält“ Hut
    dlg.get_by_test_id("condition-add").click()
    row = dlg.get_by_test_id("condition")
    pick_value(row, "cond-value", "Objekte (Liste)")
    row.get_by_test_id("cond-op").get_by_role("button").click()
    page.get_by_role("option", name="enthält", exact=True).click()
    row.get_by_test_id("cond-label").get_by_role("combobox").fill("Hu")
    page.get_by_role("option", name=re.compile("^Hut")).click()
    # Top 2 by Anzahl von … Hut
    dlg.get_by_role("textbox", name="Anzahl").fill("2")
    pick_value(dlg, "category-by", "Anzahl von …")
    dlg.get_by_test_id("category-selection").get_by_role("combobox").fill("Hut")
    page.get_by_role("option", name=re.compile("^Hut")).click()
    dlg.get_by_test_id("category-one").get_by_role("textbox").fill("Hut")
    dlg.get_by_test_id("category-many").get_by_role("textbox").fill("Hüte")
    dlg.get_by_test_id("category-verdict-prompt").fill("Wer trägt den schönsten Hut?")
    # the live preview (debounced) shows the current winners
    preview = dlg.get_by_test_id("category-preview")
    expect(preview.get_by_test_id("category-preview-matched")).to_have_text("5 Fotos passen")
    expect(preview.get_by_role("img")).to_have_count(2)
    previews = wall.sent("POST", "/categories/preview")
    assert previews and previews[-1]["spec"]["select"]["count"] == 2
    shot(page, "ui1_category_editor_desktop")

    dlg.get_by_test_id("category-save").click()
    expect(toast(page)).to_contain_text("„Hutträger“ angelegt.")
    (body,) = wall.sent("POST", "/categories")
    assert body["id"] == "huttraeger"
    assert body["spec"] == {
        "emoji": "🎩",
        "title": "Hutträger",
        "line": "",
        "where": [{"value": "objects", "op": "contains", "operand": "hat"}],
        "select": {"by": "objects.count:hat", "order": "top", "count": 2, "then_by": [],
                   "one_per_guest": False},
        "label": {"value": None, "style": "count", "one": "Hut", "many": "Hüte"},
        "verdict": {"prompt": "Wer trägt den schönsten Hut?"},
    }  # fmt: skip
    expect(page.locator("[data-category=huttraeger]")).to_contain_text("Hutträger")
    assert errors(page) == []


def test_edit_order_switch_and_delete(desktop_page: Page, live: LiveServer, wall: FakeWall) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=livewall")
    cats = page.get_by_test_id("wall-categories")
    # ↑ moves Grinsekatzen first
    page.get_by_role("button", name="Grinsekatzen nach oben").click()
    expect(cats.locator("[data-category]").first).to_have_attribute("data-category", "grinsekatzen")
    assert wall.sent("PUT", "/categories/order")[-1] == {
        "ids": ["grinsekatzen", "volles_haus", "eroeffnung"]
    }
    # the switch saves at once
    cats.locator("[data-category=volles_haus]").get_by_text("Zeigen", exact=True).click()
    expect(page.get_by_role("switch", name="Volles Haus zeigen")).not_to_be_checked()
    assert wall.sent("PUT", "/categories/volles_haus")[-1]["enabled"] is False

    # edit: Anzahl 3 → 4, a tie-breaker, a server error lands at its field
    cats.locator("[data-category=volles_haus]").get_by_test_id("category-edit").click()
    dlg = sheet(page)
    expect(dlg.get_by_role("heading", name="Kategorie bearbeiten")).to_be_visible()
    expect(dlg.get_by_test_id("condition")).to_have_count(1)
    expect(dlg.get_by_test_id("cond-a").get_by_role("textbox")).to_have_value("3")
    dlg.get_by_role("textbox", name="Anzahl").fill("11")
    dlg.get_by_test_id("category-save").click()
    expect(dlg.get_by_text("Bitte eine ganze Zahl von 1 bis 10.")).to_be_visible()
    dlg.get_by_role("textbox", name="Anzahl").fill("4")
    dlg.get_by_test_id("category-then-add").click()
    pick_value(dlg, "category-then-by", "Lächeln")
    dlg.get_by_test_id("category-save").click()
    expect(toast(page)).to_contain_text("„Volles Haus“ gespeichert.")
    put = wall.sent("PUT", "/categories/volles_haus")[-1]
    assert put["spec"]["select"]["count"] == 4
    assert put["spec"]["select"]["then_by"] == [{"by": "smiles", "order": "top"}]
    assert put["enabled"] is False

    # delete a preset, then bring it back
    cats.locator("[data-category=volles_haus]").get_by_test_id("category-edit").click()
    sheet(page).get_by_test_id("category-delete").click()
    confirm = page.get_by_test_id("confirm").get_by_role("alertdialog")
    expect(confirm).to_contain_text("Vorlagen wiederherstellen")
    confirm.get_by_role("button", name="Löschen").click()
    expect(cats.locator("[data-category=volles_haus]")).to_have_count(0)
    assert len(wall.sent("DELETE", "/categories/volles_haus")) == 1
    page.get_by_test_id("category-restore").click()
    expect(toast(page)).to_contain_text("1 Vorlage wiederhergestellt.")
    expect(cats.locator("[data-category=volles_haus]")).to_have_count(1)
    assert errors(page) == []


def test_server_error_shows_at_the_field(
    desktop_page: Page, live: LiveServer, wall: FakeWall
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=livewall")
    page.get_by_test_id("category-new").click()
    dlg = sheet(page)
    dlg.get_by_role("textbox", name="Titel", exact=True).fill("Fehler")
    dlg.get_by_test_id("category-one").get_by_role("textbox").fill("Person")
    dlg.get_by_test_id("category-many").get_by_role("textbox").fill("Personen")
    dlg.get_by_test_id("category-save").click()
    title = dlg.get_by_test_id("category-title")
    expect(title).to_contain_text("Titel: Dieser Titel geht nicht.")
    assert len(wall.sent("POST", "/categories")) == 1
    assert errors(page, 400) == []


def test_category_editor_on_a_phone(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    install(page)
    goto(page, live, "/admin/manage?tab=livewall")
    page.get_by_test_id("category-new").click()
    dlg = sheet(page)
    dlg.get_by_test_id("condition-add").click()
    expect(dlg.get_by_test_id("condition")).to_be_visible()
    assert no_horizontal_scroll(page)
    shot(page, "ui1_category_editor_phone")
    assert errors(page) == []
