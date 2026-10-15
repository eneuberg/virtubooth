"""ML-Pipeline admin (`?tab=ml`): the nav item, the five cards, the API key (only
„gesetzt“ after saving, never the key), analyzers, properties, budget, test image.

D1/D2 build the backend in parallel, so `page.route` serves the wall admin fake of
test_wall_admin_e2e.py plus the external-AI routes of PLAN-NIGHT §4.4.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer, shot
from .conftest import beer_jpeg, errors, goto, no_horizontal_scroll, toast
from .test_wall_admin_e2e import WALL_EXTENSION, FakeWall

pytestmark = pytest.mark.e2e

PREFIX = "/api/x/wall/admin"
SECRET = "sk-ant-api03-e2e-geheim-0123456789"

BUDGET = {"party_usd": 5.0, "party_calls": None, "daily_usd": 2.0, "daily_calls": None}


class MlFake(FakeWall):
    """The wall admin fake plus /llm…, /test-image (PLAN-NIGHT §4.4)."""

    def __init__(self) -> None:
        super().__init__()
        self.llm: dict[str, Any] = {
            "enabled": True,
            "provider": "anthropic",
            "model": "claude-haiku-5-5",
            "poll": True,
            "poll_interval_s": 180,
            "detect": {"external": False},
            "effort": "low",
            "image_max_px": 1024,
            "budget": dict(BUDGET),
            "rev": 1,
            "updated_at": None,
            "by": None,
        }
        self.key: dict[str, Any] = {"set": False, "set_at": None, "provider": None, "valid": False}
        self.blocked = False
        self.props: list[dict[str, Any]] = [
            {
                "id": 1,
                "name": "coolness",
                "prompt": "Bewerte, wie cool jedes Objekt ist.",
                "created_at": "2026-10-15T19:00:00Z",
                "archived_at": None,
                "scored_photos": 42,
                "last_scored_at": "2026-10-15T20:00:00Z",
            }
        ]

    def llm_status(self) -> dict[str, Any]:
        return {
            "config": self.llm,
            "key": self.key,
            "providers": [
                {"id": "anthropic", "title": "Anthropic (Claude, USA)", "eu": False,
                 "available": True, "reason": None, "vision": True, "thinking": True,
                 "currency": "USD"},
                {"id": "deutschlandgpt", "title": "DeutschlandGPT (Claude, Deutschland)",
                 "eu": True, "available": True, "reason": None, "vision": False,
                 "thinking": True, "currency": "EUR"},
            ],
            "models": [
                {"id": "claude-haiku-5-5", "provider": "anthropic", "title": "Claude Haiku 5.5", "usd_in_mtok": 1,
                 "usd_out_mtok": 5, "currency": "USD", "price_in_mtok": 1, "price_out_mtok": 5},
                {"id": "claude-sonnet-5-5", "provider": "anthropic", "title": "Claude Sonnet 5.5", "usd_in_mtok": 3,
                 "usd_out_mtok": 15, "currency": "USD", "price_in_mtok": 3, "price_out_mtok": 15},
                {"id": "claude-opus-5-5", "provider": "anthropic", "title": "Claude Opus 5.5", "usd_in_mtok": 5,
                 "usd_out_mtok": 25, "currency": "USD", "price_in_mtok": 5, "price_out_mtok": 25},
                {"id": "claude-haiku-5.5", "provider": "deutschlandgpt", "title": "Claude Haiku 5.5",
                 "usd_in_mtok": 0.913, "usd_out_mtok": 4.543, "currency": "EUR",
                 "price_in_mtok": 0.83, "price_out_mtok": 4.13},
            ],
            "poller": {"state": "blocked" if self.blocked else "idle", "last_poll_at": None,
                       "next_poll_at": None, "last_error": None},
            "detection": {"mode": self.mode(),
                          "state": "idle" if self.mode() == "ai" else "off",
                          "pending": 0, "done": 4, "failed": 0, "last_run_at": None,
                          "last_error": None,
                          # the local detector stands in while the budget is used up
                          "fallback": 2 if self.blocked else 0,
                          "fallback_reason": "Budget aufgebraucht" if self.blocked else None,
                          "fallback_now": "Budget aufgebraucht" if self.blocked else None,
                          "stats": {"processed": 4, "errors": 0, "avg_ms": 2400, "last_ms": 1900},
                          "cost_usd": 0.4},
            "usage": {
                "party": {"calls": 12, "input_tokens": 30000, "output_tokens": 4000,
                          "cost_usd": 5.0 if self.blocked else 1.25},
                "today": {"calls": 5, "input_tokens": 9000, "output_tokens": 1000,
                          "cost_usd": 0.5},
                "by_kind": [
                    {"kind": "detect", "ref": None, "calls": 4, "tokens": 12000, "cost_usd": 0.4},
                    {"kind": "property", "ref": "coolness", "calls": 6, "tokens": 18000,
                     "cost_usd": 0.7},
                    {"kind": "verdict", "ref": "coolstes_objekt", "calls": 2, "tokens": 4000,
                     "cost_usd": 0.15},
                ],
                "budget": self.llm["budget"],
                "blocked": self.blocked,
                "reason": "Das Party-Budget ist aufgebraucht." if self.blocked else None,
            },
        }  # fmt: skip

    def mode(self) -> str:
        if self.llm["detect"]["external"]:
            return "ai"
        return "off" if "objects" in self.disabled_analyzers else "local"

    def answer(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        match method, path:
            case "GET", "/llm":
                return 200, self.llm_status()
            case "PUT", "/llm/object-detection":
                mode = body["mode"]
                self.llm = {**self.llm, "detect": {"external": mode == "ai"}}
                rest = [n for n in self.disabled_analyzers if n != "objects"]
                self.disabled_analyzers = rest if mode == "local" else [*rest, "objects"]
                return 200, self.llm_status()
            case "PUT", "/llm/config":
                self.llm = {**self.llm, **body, "rev": self.llm["rev"] + 1}
                return 200, self.llm_status()
            case "PUT", "/llm/key":
                self.key = {"set": True, "set_at": "2026-10-15T20:00:00Z",
                            "provider": body["provider"], "valid": True}  # fmt: skip
                return 200, self.key
            case "DELETE", "/llm/key":
                self.key = {"set": False, "set_at": None, "provider": None, "valid": False}
                return 200, self.key
            case "POST", "/llm/key/test":
                return 200, {"ok": True, "message": "Der Schlüssel funktioniert."}
            case "POST", "/llm/poll":
                return 200, {"started": True, "reason": None}
            case "GET", "/llm/properties":
                return 200, {"properties": self.props}
            case "POST", "/llm/properties":
                prop = {"id": len(self.props) + 1, **body, "created_at": "2026-10-15T21:00:00Z",
                        "archived_at": None, "scored_photos": 0, "last_scored_at": None}  # fmt: skip
                self.props.append(prop)
                return 201, prop
            case "POST", "/test-image":
                return 200, TEST_RESULT
        m = re.fullmatch(r"/llm/properties/([a-z0-9_]+)/(archive|unarchive)", path)
        if m and method == "POST":
            prop = next(p for p in self.props if p["name"] == m[1])
            prop["archived_at"] = "2026-10-15T21:00:00Z" if m[2] == "archive" else None
            return 200, prop
        return super().answer(method, path, body)


TEST_RESULT = {
    "width": 800,
    "height": 600,
    "local": {
        "width": 800,
        "height": 600,
        "facts": {"faces": 2, "brightness": 0.41},
        "boxes": [
            {"kind": "face", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "Gesicht",
             "score": 0.9},
        ],
        "details": [{"label": "Gesichter", "value": "2"}],
        "objects": [{"label": "wine glass", "label_de": "Weinglas", "score": 0.87,
                     "box": {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.2}}],
        "durations_ms": {"basic": 11, "faces": 150},
        "error": None,
        "skipped": {},
    },
    "external": None,
    "merged": [{"idx": 0, "label": "wine glass", "label_de": "Weinglas", "score": 0.87,
                "box": {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.2}, "sources": ["local"],
                "local_pos": 0, "ai_pos": None}],
}  # fmt: skip


def install(page: Page) -> MlFake:
    fake = MlFake()

    def extensions(route: Any) -> None:
        response = route.fetch()
        data = response.json()
        data["extensions"].append(copy.deepcopy(WALL_EXTENSION))
        route.fulfill(response=response, json=data)

    page.route("**/api/admin/extensions", extensions)
    page.route(f"**{PREFIX}/**", fake.handle)
    return fake


@pytest.fixture
def ml(desktop_page: Page) -> MlFake:
    return install(desktop_page)


CARDS = ["Modelle", "Testbild", "Externe KI", "Eigenschaften", "Budget"]


def test_nav_item_opens_the_five_cards(desktop_page: Page, live: LiveServer, ml: MlFake) -> None:
    page = desktop_page
    ml.worker = {"processed": 1234, "rss_mb": 411.6, "load_errors": {"age": "Modell kaputt"}}
    goto(page, live, "/admin/manage")
    nav = page.get_by_role("navigation", name="Verwaltung")
    expect(nav.get_by_role("link", name="ML-Pipeline")).to_be_visible()
    links = [t.strip() for t in nav.get_by_role("link").all_inner_texts()]
    # directly after Live-Wall
    assert [t for t in links if t.startswith(("Live-Wall", "ML-Pipeline"))] == [
        "Live-Wall",
        "ML-Pipeline",
    ]
    nav.get_by_role("link", name="ML-Pipeline").click()
    page.wait_for_url(live.url("/admin/manage?tab=ml"))
    expect(page.get_by_role("heading", name="ML-Pipeline", level=1)).to_be_focused()
    headings = page.get_by_role("heading", level=2)
    expect(headings).to_have_text(CARDS)

    # Modelle: what, size, numbers, queue, the worker's heartbeat, the freeze note
    row = page.locator("[data-analyzer=objects]")
    expect(row.get_by_test_id("ml-analyzer-size")).to_have_text("12 MB")
    expect(row.get_by_test_id("ml-analyzer-stats")).to_have_text(
        "Ø 340 ms · zuletzt 290 ms · 128 Fotos · 2 Fehler"
    )
    expect(page.get_by_test_id("ml-queue")).to_have_text(
        "Warteschlange: 3 Fotos (ältestes seit 12 s)"
    )
    expect(page.get_by_test_id("wall-worker")).to_contain_text("läuft")
    expect(page.get_by_test_id("wall-worker-processed")).to_have_text("1.234 Fotos")
    expect(page.get_by_test_id("wall-worker-rss")).to_have_text("412 MB")
    expect(page.get_by_test_id("wall-worker-load-errors")).to_contain_text("Alter schätzen")
    expect(page.get_by_test_id("ml-freeze-note")).to_have_text(
        "Analysen werden einmal gemacht und danach nicht mehr verändert. "
        "Änderungen gelten für neue Fotos."
    )
    expect(page.get_by_role("button", name=re.compile("analysieren", re.I))).to_have_count(0)
    assert no_horizontal_scroll(page)
    shot(page, "ui1_ml_desktop", 600)
    assert errors(page) == []


def test_key_shows_only_gesetzt_after_save(
    desktop_page: Page, live: LiveServer, ml: MlFake
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=ml")
    state = page.get_by_test_id("ml-key-state")
    expect(state).to_have_text("nicht gesetzt")
    field = page.get_by_label("API-Schlüssel", exact=True)
    expect(field).to_have_attribute("type", "password")
    expect(field).to_have_value("")
    field.fill(SECRET)
    page.get_by_test_id("ml-key-save").click()
    expect(state).to_have_text("gesetzt")
    expect(toast(page)).to_contain_text("API-Schlüssel gespeichert.")
    assert ml.sent("PUT", "/llm/key") == [{"provider": "anthropic", "key": SECRET}]
    expect(page.get_by_label("API-Schlüssel", exact=True)).to_have_count(0)
    assert SECRET not in page.content()
    expect(page.get_by_test_id("ml-key-replace")).to_have_text("Schlüssel ersetzen")

    # a reload: still only the state; "Schlüssel ersetzen" opens an empty field
    goto(page, live, "/admin/manage?tab=ml")
    expect(state).to_have_text("gesetzt")
    assert SECRET not in page.content()
    page.get_by_test_id("ml-key-replace").click()
    expect(page.get_by_label("Neuer API-Schlüssel")).to_have_value("")
    page.get_by_role("button", name="Abbrechen").click()
    page.get_by_test_id("ml-key-test").click()
    expect(toast(page)).to_contain_text("Der Schlüssel funktioniert.")
    page.get_by_test_id("ml-key-clear").click()
    page.get_by_test_id("confirm").get_by_role("button", name="Schlüssel löschen").click()
    expect(state).to_have_text("nicht gesetzt")
    assert errors(page) == []


def test_external_ai_detection_poll_properties_and_budget(
    desktop_page: Page, live: LiveServer, ml: MlFake
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=ml")
    # Externe KI: only switch, provider, model, Denkaufwand (and the key): one PUT of those
    card = page.get_by_test_id("wall-card-externe-ki")
    expect(card.get_by_test_id("ml-detect-external")).to_have_count(0)
    expect(card.get_by_test_id("ml-llm-poll")).to_have_count(0)
    card.get_by_test_id("ml-llm-model").get_by_role("button").click()
    page.get_by_role("option", name=re.compile("^Claude Sonnet 5.5")).click()
    card.get_by_test_id("ml-llm-effort").get_by_role("button").click()
    page.get_by_role("option", name="mittel").click()
    card.get_by_test_id("ml-llm-save").click()
    expect(toast(page)).to_contain_text("KI-Einstellungen gespeichert.")
    (cfg,) = ml.sent("PUT", "/llm/config")
    assert cfg == {"enabled": True, "provider": "anthropic", "model": "claude-sonnet-5-5",
                   "effort": "medium"}  # fmt: skip

    # Modelle: object detection either/or, the AI row next to the local one
    choice = page.get_by_test_id("ml-object-detection")
    expect(choice.get_by_role("radio", name="Lokal")).to_be_checked()
    expect(page.get_by_test_id("ml-local-detect-active")).to_have_text("aktiv")
    choice.get_by_text("KI", exact=True).click()
    expect(page.get_by_test_id("ml-ai-detect-active")).to_have_text("aktiv")
    expect(page.get_by_test_id("ml-local-detect-active")).to_have_text("aus")
    expect(page.get_by_test_id("ml-detection-state")).to_have_text("bereit")
    assert ml.sent("PUT", "/llm/object-detection") == [{"mode": "ai"}]
    # no key yet: the red hint at the AI row and at the poll
    hint = page.locator("[data-analyzer=objects-ai]").get_by_test_id("ml-ai-off-hint")
    expect(hint).to_contain_text("Kein gültiger API-Schlüssel")
    expect(page.get_by_test_id("ml-part-poll").get_by_test_id("ml-ai-off-hint")).to_be_visible()

    # Eigenschaften: the poll's switch and interval, saved on their own
    poll = page.get_by_test_id("ml-part-poll")
    poll.get_by_role("textbox", name="Abfrage alle … Minuten").fill("5")
    poll.get_by_test_id("ml-llm-poll").click()
    poll.get_by_test_id("ml-poll-save").click()
    expect(toast(page)).to_contain_text("Abfrage gespeichert.")
    assert ml.sent("PUT", "/llm/config")[-1] == {"poll": False, "poll_interval_s": 300}

    # a property: the warning, create, archive (no edit, no delete)
    page.get_by_test_id("ml-property-new").click()
    sheet = page.get_by_test_id("ml-property-sheet").get_by_role("dialog")
    expect(sheet.get_by_test_id("ml-property-warning")).to_contain_text(
        "Name und Prompt lassen sich später nicht ändern."
    )
    sheet.get_by_role("textbox", name="Name").fill("most_giraffe")
    sheet.get_by_test_id("ml-property-prompt").fill("Wie sehr ähnelt das Objekt einer Giraffe?")
    sheet.get_by_test_id("ml-property-create").click()
    expect(toast(page)).to_contain_text("Eigenschaft „most_giraffe“ angelegt.")
    row = page.locator("[data-property=most_giraffe]")
    row.get_by_role("button", name="Archivieren").click()
    expect(row).to_contain_text("Archiviert")
    assert len(ml.sent("POST", "/llm/properties/most_giraffe/archive")) == 1
    expect(row.get_by_role("button", name=re.compile("Bearbeiten|Löschen"))).to_have_count(0)

    # budget: limits, then the stop banner
    page.get_by_role("textbox", name="Pro Tag (USD)").fill("3,50")
    page.get_by_role("button", name="Limits speichern").click()
    expect(toast(page)).to_contain_text("Limits gespeichert.")
    assert ml.sent("PUT", "/llm/config")[-1]["budget"]["daily_usd"] == 3.5
    ml.blocked = True
    goto(page, live, "/admin/manage?tab=ml")
    expect(page.get_by_test_id("ml-budget-blocked")).to_contain_text(
        "Budget erreicht – externe KI pausiert"
    )
    # meanwhile the local detector stands in for the AI: the AI row says so
    ai_row = page.locator("[data-analyzer=objects-ai]")
    expect(ai_row.get_by_test_id("ml-ai-detect-fallback-count")).to_have_text(
        "2 Fotos lokal statt KI · zuletzt: Budget aufgebraucht"
    )
    expect(ai_row.get_by_test_id("ml-ai-detect-fallback-now")).to_contain_text(
        "Gerade erkennt das lokale Modell statt der KI (Budget aufgebraucht)"
    )
    expect(page.get_by_test_id("ml-usage-table")).to_contain_text("Eigenschaft „coolness“")
    assert errors(page) == []


def test_test_image(desktop_page: Page, live: LiveServer, ml: MlFake) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=ml")
    # no key: the AI can't take it (the red hint says why)
    expect(page.get_by_role("checkbox", name="Auch an die KI schicken (kostet)")).to_be_disabled()
    expect(
        page.get_by_test_id("wall-card-testbild").get_by_test_id("ml-ai-off-hint")
    ).to_be_visible()
    with page.expect_file_chooser() as chooser:
        page.get_by_test_id("ml-test-file").click()
    chooser.value.set_files(
        files=[{"name": "test.jpg", "mimeType": "image/jpeg", "buffer": beer_jpeg()}]
    )
    expect(page.get_by_test_id("ml-test-filename")).to_contain_text("test.jpg")
    page.get_by_test_id("ml-test-run").click()
    result = page.get_by_test_id("ml-test-result")
    expect(result.get_by_test_id("ml-test-objects")).to_contain_text("Weinglas")
    expect(result.get_by_test_id("analysis-box")).to_have_count(2)
    expect(result.get_by_test_id("ml-test-durations")).to_contain_text("Gesichter 150 ms")
    expect(result.get_by_role("img", name="Testbild")).to_be_visible()
    assert errors(page) == []


def test_ml_section_on_a_phone(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    install(page)
    goto(page, live, "/admin/manage?tab=ml")
    expect(page.get_by_role("heading", level=2)).to_have_text(CARDS)
    assert no_horizontal_scroll(page)
    shot(page, "ui1_ml_phone", 600)
    page.get_by_role("heading", name="Budget", level=2).scroll_into_view_if_needed()
    shot(page, "ui1_ml_phone_budget", 300)
    assert errors(page) == []


# every box of the analyzer settings form: labels, fields, helper texts, „Speichern“
OVERLAPS = """(form) => {
    const parts = [...form.querySelectorAll('label, input, [slot=description], button')]
        .map((el) => [el, el.getBoundingClientRect()]);
    const out = [];
    for (const [i, [a, ra]] of parts.entries()) {
        for (const [b, rb] of parts.slice(i + 1)) {
            if (a.contains(b) || b.contains(a)) continue;
            const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
            const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
            if (w > 0.5 && h > 0.5) out.push(`${a.textContent || a.tagName} / ${b.textContent || b.tagName}`);
        }
    }
    const f = form.getBoundingClientRect();
    for (const [el, r] of parts)
        if (r.left < f.left - 0.5 || r.right > f.right + 0.5) out.push(`${el.textContent || el.tagName} sticks out`);
    return out;
}"""


@pytest.mark.parametrize(
    "viewport",
    [{"width": 1280, "height": 800}, {"width": 768, "height": 1024}, {"width": 320, "height": 640}],
    ids=["laptop", "tablet", "small-phone"],
)
def test_analyzer_settings_do_not_overlap(
    browser: Any, live: LiveServer, viewport: dict[str, int]
) -> None:
    """„Mindest-Sicherheit“ and „Höchstens Objekte pro Foto“ (the real analyzers): each
    label, field, range and the button in its own box, inside the card (they ran into
    each other in the 1280 px laptop's narrow column)."""
    from .conftest import admin_context, login_api

    ctx = admin_context(browser, viewport)
    try:
        page = ctx.new_page()
        login_api(page, live)
        goto(page, live, "/admin/manage?tab=ml")
        forms = page.get_by_test_id("ml-analyzer-settings")
        expect(forms.first).to_be_visible()
        objects = page.locator("[data-analyzer=objects] [data-testid=ml-analyzer-settings]")
        expect(objects.get_by_role("textbox", name="Höchstens Objekte pro Foto")).to_be_visible()
        for i in range(forms.count()):
            form = forms.nth(i)
            form.scroll_into_view_if_needed()
            assert form.evaluate(OVERLAPS) == []
        assert no_horizontal_scroll(page)
        objects.scroll_into_view_if_needed()
        shot(page, f"ml_analyzer_settings_{viewport['width']}", 300)
    finally:
        ctx.close()


MISSING_REASON = "Modell fehlt: yunet. Oben „Modelle herunterladen“ drücken."


def test_models_download_and_switches_of_analyzers_that_cannot_run(
    desktop_page: Page, live: LiveServer, ml: MlFake
) -> None:
    page = desktop_page
    # ML packages there, models not (image built with VB_BAKE_MODELS=0)
    ml.models.update(missing=["yunet", "face_landmarker"], missing_mb=4, can_download=True)
    ml.unavailable = {"faces": MISSING_REASON, "objects": MISSING_REASON}

    def start_download() -> dict[str, Any]:
        ml.models.update(can_download=False, download={
            "state": "running", "current": "face_landmarker", "models": ["yunet", "face_landmarker"],
            "done_bytes": 1_500_000, "total_bytes": 4_000_000, "error": None, "finished_at": None,
        })  # fmt: skip
        return ml.status()

    ml.start_download = start_download  # type: ignore[method-assign]
    goto(page, live, "/admin/manage?tab=ml")
    missing = page.get_by_test_id("ml-models-missing")
    expect(missing).to_contain_text("2 Modelle fehlen")
    faces = page.locator("[data-analyzer=faces]")
    expect(faces.get_by_test_id("ml-analyzer-reason")).to_have_text(MISSING_REASON)
    expect(faces).to_contain_text("läuft nicht")

    # the switch of an analyzer that can't run: off, then on again (the bug)
    switch = page.get_by_role("switch", name="Gesichter an")
    label = faces.locator("label:has([role=switch])")
    expect(switch).to_be_checked()
    expect(switch).to_be_enabled()
    label.click()
    expect(switch).not_to_be_checked()
    expect(switch).to_be_enabled()
    label.click()
    expect(switch).to_be_checked()
    assert [b["enabled"] for b in ml.sent("PUT", "/analysis/analyzers/faces")] == [False, True]

    # the download: one POST without a body, then the progress
    missing.get_by_role("button", name="Modelle herunterladen").click()
    expect(page.get_by_test_id("ml-models-progress")).to_have_text("2 von 4 MB")
    assert ml.sent("POST", "/analysis/models/download") == [None]

    # done (the worker beats): the analyzers run, the button is gone
    ml.models.update(missing=[], missing_mb=0, download={
        **ml.models["download"], "state": "done", "current": None, "done_bytes": 4_000_000,
        "finished_at": "2026-10-15T20:00:00Z",
    })  # fmt: skip
    ml.unavailable = {}
    goto(page, live, "/admin/manage?tab=ml")
    expect(page.get_by_test_id("ml-models-done")).to_contain_text("Modelle heruntergeladen")
    expect(page.get_by_role("button", name="Modelle herunterladen")).to_have_count(0)
    expect(faces.get_by_test_id("ml-analyzer-reason")).to_have_count(0)
    assert no_horizontal_scroll(page)
    assert errors(page) == []


def test_without_the_ml_packages_it_says_how_to_fix_it(
    desktop_page: Page, live: LiveServer, ml: MlFake
) -> None:
    page = desktop_page
    ml.models.update(ml=False, missing=["yunet"], missing_mb=0.2, can_download=False)
    ml.worker = {
        "ml": False,
        "message": "Ohne KI-Paket: nur Bildwerte (Helligkeit, Farbe, Schärfe).",
    }
    goto(page, live, "/admin/manage?tab=ml")
    box = page.get_by_test_id("ml-packages-missing")
    expect(box).to_contain_text("KI-Pakete fehlen in diesem Server-Image")
    expect(box).to_contain_text("VB_ML")
    expect(box).to_contain_text("Redeploy")
    expect(page.get_by_role("button", name="Modelle herunterladen")).to_have_count(0)
    assert errors(page) == []
