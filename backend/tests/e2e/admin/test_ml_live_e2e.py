"""The ML-Pipeline, the category editor and the wall's verdict against the REAL
backend (INT2): no `page.route` fakes. The external AI is a fake provider plugged
into the server's own LlmService (no network); the photo analysis is the real
`jobs.claim/finish` path the worker uses (the worker itself is off here, except in
the test-image test, which starts the real worker process)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.objects import DetectedObject
from virtubooth.extensions.wall.llm.service import LlmService

from ...llm_fakes import FakeProvider
from ..conftest import LOADED, LiveServer, track_errors, wait_until_ready
from ..wall.conftest import TV
from .conftest import Guest, beer_jpeg, errors, goto, toast, wait_until

pytestmark = pytest.mark.e2e

SECRET = "sk-ant-api03-E2E-SECRET-never-shown-0123456789"
WALL_PASSWORD = "wall-geheim-1"
ADMIN = "/api/x/wall/admin"


@pytest.fixture
def e2e_settings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The test-image test: the wall's real analysis worker runs (spawned at start)."""
    if request.node.name.startswith("test_test_image"):
        monkeypatch.setenv("VB_WALL_WORKER", "on")
    return {}


def api(page: Page, live: LiveServer, method: str, path: str, body: Any = None) -> Any:
    r = page.context.request.fetch(
        live.url(path),
        method=method,
        headers={"Origin": live.base_url, "Content-Type": "application/json"},
        data=json.dumps(body) if body is not None else None,
    )
    assert r.ok, f"{method} {path}: {r.status} {r.text()}"
    return r.json()


def analysed(live: LiveServer, public_id: str, labels: list[tuple[str, str]]) -> int:
    """What the worker does for a photo: claim it, store facts and the local objects,
    or (either/or) none and queue it for the external AI while that is the detector."""
    db = live.core.db
    pid = live.core.repos.photos.internal_id(public_id)
    assert pid is not None
    claimed = jobs.claim(db)
    assert claimed is not None and claimed.id == pid
    ai = jobs.ai_detection_active(live.core.repos.app_settings)
    objs = [DetectedObject(en, de, 0.8, (0.1 * i, 0.1, 0.2, 0.3)) for i, (en, de) in
            enumerate(labels)]  # fmt: skip
    assert jobs.finish(db, pid, facts={"brightness": 0.5, "faces": 1.0, "people": 1.0},
                       data={}, versions={"basic": "1"}, objects_found=[] if ai else objs,
                       objects_model=None if ai else "e2e@1",
                       objects_skipped=jobs.AI_ACTIVE if ai else None,
                       ai_detect=ai)  # fmt: skip
    return pid


@pytest.fixture
def admin(browser: Browser, live: LiveServer) -> Iterator[Page]:
    from .conftest import DESKTOP_VIEWPORT, admin_context, login_api

    ctx = admin_context(browser, DESKTOP_VIEWPORT)
    page = track_errors(ctx.new_page())
    login_api(page, live)
    yield page
    ctx.close()


@pytest.fixture
def fake(live: LiveServer) -> FakeProvider:
    """The external AI: the server's own LlmService (started by the wall) talks to it."""
    provider = FakeProvider(objects=[DetectedObject("bow tie", "Fliege", 0.9, None)])

    def scores(lines: Any) -> dict[str, list[float | None]]:
        return {x.ref: [0.9 if lb == "sunglasses" else 0.2 for lb in x.labels] for x in lines}

    provider.score_fn = scores
    svc = LlmService.of(live.core)
    svc.provider_factory = lambda _pid, _key: provider
    svc.forget_provider()
    return provider


def test_ml_pipeline_categories_and_the_wall_verdict(
    admin: Page, browser: Browser, live: LiveServer, fake: FakeProvider
) -> None:
    page = admin
    # two guests: Fuchs allows everything, Otter says „Keine Weitergabe an externe KI“
    fuchs = Guest(live)
    otter = Guest(live)
    r = fuchs.client.patch("/api/me", json={"display_name": "Partyfuchs"})
    assert r.status_code == 200, r.text
    assert otter.client.put("/api/me/external-ai", json={"opt_out": True}).status_code == 200
    cool = fuchs.upload()
    other = otter.upload()
    # analysed while the local detector is the one (the default)
    analysed(live, other, [("person", "Person"), ("hat", "Hut")])
    analysed(live, cool, [("person", "Person"), ("sunglasses", "Sonnenbrille")])

    # the wall: no delay (the categories only see photos the wall shows), categories only
    api(page, live, "PUT", f"{ADMIN}/password", {"password": WALL_PASSWORD})
    config = api(page, live, "GET", f"{ADMIN}/config")["config"]
    config["delay_s"] = 0
    config["playlist"] = [
        {"mode": m, "enabled": m == "categories", "duration_s": 600}
        for m in ("spotlight", "gallery", "categories")
    ]
    config["categories"] = {"per_category_s": 60}
    api(page, live, "PUT", f"{ADMIN}/config", config)

    # ML-Pipeline: the real analyzers, the key (write-only), the switch, a property
    goto(page, live, "/admin/manage?tab=ml")
    expect(page.locator("[data-analyzer=objects]")).to_be_visible()
    expect(page.get_by_test_id("ml-key-state")).to_have_text("nicht gesetzt")
    page.get_by_label("API-Schlüssel", exact=True).fill(SECRET)
    page.get_by_test_id("ml-key-save").click()
    expect(page.get_by_test_id("ml-key-state")).to_have_text("gesetzt")
    assert SECRET not in page.content()
    stored = live.core.db.one("SELECT value FROM settings WHERE key='x.llm.key'")
    assert stored is not None and SECRET not in stored["value"]
    page.get_by_test_id("ml-llm-enabled").click()
    page.get_by_test_id("ml-llm-save").click()
    expect(toast(page)).to_contain_text("KI-Einstellungen gespeichert.")
    page.get_by_test_id("ml-property-new").click()
    sheet = page.get_by_test_id("ml-property-sheet").get_by_role("dialog")
    sheet.get_by_role("textbox", name="Name").fill("coolness")
    sheet.get_by_test_id("ml-property-prompt").fill("Wie cool ist jedes Objekt?")
    sheet.get_by_test_id("ml-property-create").click()
    expect(toast(page)).to_contain_text("Eigenschaft „coolness“ angelegt.")
    expect(page.locator("[data-property=coolness]")).to_be_visible()

    # object detection either/or: „KI“ in Modelle switches the local detector off
    page.get_by_test_id("ml-object-detection").get_by_text("KI", exact=True).click()
    expect(page.get_by_test_id("ml-ai-detect-active")).to_have_text("aktiv")
    expect(page.get_by_test_id("ml-local-detect-active")).to_have_text("inaktiv")
    expect(page.get_by_test_id("ml-object-detection-error")).to_have_count(0)
    assert "objects" in jobs.disabled_analyzers(live.core.repos.app_settings)
    # only photos the pipeline finishes from now on go out (no backfill of the two above),
    # and of those only Fuchs's (Otter opted out)
    try:
        new_other = otter.upload()
        new_cool = fuchs.upload()
    finally:
        fuchs.client.close()
        otter.client.close()
    analysed(live, new_cool, [])
    analysed(live, new_other, [])
    wait_until(lambda: len(fake.detected) >= 1, timeout=15, what="detection")
    page.wait_for_timeout(500)
    assert len(fake.detected) == 1
    new_id = live.core.repos.photos.internal_id(new_cool)
    runs = live.core.db.all(
        "SELECT photo_id, source FROM photo_detection_runs WHERE source != 'local'"
    )
    assert [(r["photo_id"], r["source"]) for r in runs] == [(new_id, "claude")]
    expect(page.get_by_test_id("ml-ai-detect-state")).to_contain_text("1 fertig", timeout=15_000)

    # the editor: the coolest-object preset needs the property; switch it on
    goto(page, live, "/admin/manage?tab=livewall")
    row = page.locator("[data-category=coolstes_objekt]")
    expect(row).to_be_visible()
    row.get_by_test_id("category-edit").click()
    dlg = page.get_by_test_id("category-sheet").get_by_role("dialog")  # the editor
    expect(dlg.get_by_role("heading", name="Kategorie bearbeiten")).to_be_visible()
    # the preset leaves the task empty: the default task, shown as the placeholder
    prompt = dlg.get_by_test_id("category-verdict-prompt")
    expect(prompt).to_have_value("")
    expect(prompt).to_have_attribute("placeholder", re.compile("coolste Objekt"))
    dlg.get_by_test_id("category-save").click()
    expect(toast(page)).to_contain_text("„Das coolste Objekt“ gespeichert.")
    row.get_by_text("Zeigen", exact=True).click()
    expect(page.get_by_role("switch", name="Das coolste Objekt zeigen")).to_be_checked()

    # poll now (the button): scores, then the verdict
    goto(page, live, "/admin/manage?tab=ml")
    page.get_by_test_id("ml-poll-now").click()
    expect(toast(page)).to_contain_text("Die Abfrage läuft.")
    wait_until(
        lambda: live.core.db.one("SELECT 1 FROM wall_category_comments") is not None,
        timeout=10, what="verdict",
    )  # fmt: skip
    sent = json.dumps(
        [[x.author, x.labels] for _, lines, _ in fake.scored for x in lines]
        + [[x.author, x.labels] for _, lines in fake.verdicts for x in lines],
        ensure_ascii=False,
    )
    assert "Partyfuchs" in sent and "Otter" not in sent and "hat" not in sent
    verdict = live.core.db.one("SELECT text FROM wall_category_comments")["text"]
    assert "Partyfuchs" in verdict
    page.reload(wait_until=LOADED)
    expect(page.get_by_test_id("ml-usage-table")).to_contain_text("Eigenschaft „coolness“")

    # the admin's category list shows the verdict and the winner
    goto(page, live, "/admin/manage?tab=livewall")
    expect(page.locator("[data-category=coolstes_objekt]")).to_contain_text("Partyfuchs")

    # the TV: the verdict under the winner
    # only this category, so the wall shows it right away
    for c in api(page, live, "GET", f"{ADMIN}/categories")["categories"]:
        if c["id"] != "coolstes_objekt" and c["enabled"]:
            api(page, live, "PUT", f"{ADMIN}/categories/{c['id']}",
                {"spec": c["spec"], "enabled": False})  # fmt: skip
    ctx = browser.new_context(**TV)
    tv = track_errors(ctx.new_page())
    try:
        tv.goto(live.url("/livewall"), wait_until=LOADED)
        wait_until_ready(tv)
        login = tv.get_by_test_id("wall-login")
        login.get_by_label("Passwort").fill(WALL_PASSWORD)
        login.get_by_role("button", name="Live-Wall starten").click()
        expect(tv.get_by_test_id("wall-verdict")).to_contain_text(verdict, timeout=15_000)
        # the winning object is the headline, its score the value chip
        expect(tv.locator(".wall-cat-headline")).to_have_text(["Sonnenbrille"])
        expect(tv.locator(".wall-cat-value")).to_have_text([re.compile(r"0,9\d* Coolness")])
    finally:
        ctx.close()
    assert errors(page) == []


def test_test_image_runs_the_real_local_pipeline(admin: Page, live: LiveServer) -> None:
    page = admin
    goto(page, live, "/admin/manage?tab=ml")
    expect(page.get_by_test_id("wall-worker")).to_contain_text("läuft", timeout=60_000)
    with page.expect_file_chooser() as chooser:
        page.get_by_test_id("ml-test-file").click()
    chooser.value.set_files(
        files=[{"name": "bier.jpg", "mimeType": "image/jpeg", "buffer": beer_jpeg()}]
    )
    page.get_by_test_id("ml-test-run").click()
    result = page.get_by_test_id("ml-test-result")
    facts = result.get_by_test_id("ml-test-facts")
    expect(facts).to_contain_text("brightness", timeout=30_000)
    expect(facts).to_contain_text("sharpness")
    expect(result.get_by_test_id("ml-test-durations")).to_contain_text("ms")
    # nothing stored as a party photo
    assert live.core.db.one("SELECT COUNT(*) AS n FROM photos")["n"] == 0
    assert errors(page) == []
