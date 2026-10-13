"""The after-party tools in manage: the Instagram board (ZIP per name, the "Erledigt"
mark) and the export section (archive, timelapse, QR sheet as background jobs)."""

from __future__ import annotations

import re
import threading
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from virtubooth.services.exports import ExportService

from ..conftest import LiveServer, allow_clipboard, needs_clipboard
from .conftest import Guest, confirm_dialog, errors, goto, toast, wait_live

pytestmark = pytest.mark.e2e


def board_rows(page: Page):  # type: ignore[no-untyped-def]
    return page.get_by_test_id("insta-row")


@needs_clipboard
def test_instagram_board(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    allow_clipboard(page.context)
    anna, anna2 = guests(instagram="anna.party"), guests(instagram="anna.party")  # two phones
    ben = guests(instagram="ben_b")
    troll = guests(instagram="troll")
    guests()  # no handle
    for g in (anna, anna, anna2, ben, troll):
        g.upload()
    live.core.services.moderation.ban_user(troll.id, reason="Spam", actor="pytest")

    goto(page, live, "/admin/manage?tab=instagram")
    wait_live(page)
    expect(page.get_by_test_id("insta-count")).to_have_text("3 Namen, 4 Gäste, 3 offen")
    expect(board_rows(page)).to_have_count(3)
    first = board_rows(page).first
    expect(first).to_have_attribute("data-handle", "anna.party")  # most photos first
    expect(first).to_contain_text("3 Fotos")
    expect(first.locator("[data-photo-id]")).to_have_count(3)
    expect(first.get_by_role("link", name=anna.name)).to_have_attribute(
        "href", f"/admin/user?id={anna.id}"
    )
    # a banned guest's name gets no ZIP
    troll_row = board_rows(page).filter(has_text="@troll")
    expect(troll_row.get_by_test_id("insta-zip")).to_have_count(0)

    # copying all names leaves the banned guests out
    page.get_by_test_id("copy-all-handles").click()
    expect(toast(page)).to_contain_text("Kopiert: 2 Namen")
    assert page.evaluate("() => navigator.clipboard.readText()") == "@anna.party @ben_b"

    # the ZIP of one name
    with page.expect_download() as dl:
        first.get_by_test_id("insta-zip").click()
    assert dl.value.suggested_filename == "fotos-anna.party.zip"
    with zipfile.ZipFile(dl.value.path()) as z:
        assert len(z.namelist()) == 3

    # "Erledigt": stored on the server, the row leaves the open list
    first.get_by_text("Erledigt").click()
    expect(board_rows(page)).to_have_count(2)
    expect(page.get_by_test_id("insta-count")).to_contain_text("2 offen")
    handles = page.evaluate(
        "async () => (await (await fetch('/api/admin/instagram')).json()).handles"
    )
    assert {h["handle"]: h["done"] for h in handles}["anna.party"] is True
    page.get_by_test_id("insta-show").get_by_text("Erledigt", exact=True).click()
    expect(board_rows(page)).to_have_count(1)
    board_rows(page).first.get_by_text("Erledigt", exact=True).click()
    expect(board_rows(page)).to_have_count(0)
    page.get_by_test_id("insta-show").get_by_text("Offen", exact=True).click()
    expect(board_rows(page)).to_have_count(3)
    assert errors(page) == []


def test_instagram_done_toast_offers_undo(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    """The row leaves the open list at once: the toast says so and can take it back."""
    page = desktop_page
    guests(instagram="anna.party").upload()
    guests(instagram="ben_b").upload()
    goto(page, live, "/admin/manage?tab=instagram")
    wait_live(page)
    expect(board_rows(page)).to_have_count(2)
    board_rows(page).filter(has_text="@anna.party").get_by_text("Erledigt").click()
    expect(board_rows(page)).to_have_count(1)
    expect(toast(page)).to_contain_text("@anna.party erledigt")
    toast(page).get_by_role("button", name="Rückgängig").click()
    expect(board_rows(page)).to_have_count(2)
    expect(toast(page)).to_contain_text("@anna.party wieder offen")
    handles = page.evaluate(
        "async () => (await (await fetch('/api/admin/instagram')).json()).handles"
    )
    assert not any(h["done"] for h in handles)
    assert errors(page) == []


class Gate:
    """Makes an export runner wait until the test lets it go (to see "running")."""

    def __init__(self, live: LiveServer, kind: str) -> None:
        self.release = threading.Event()
        service = live.core.services.exports
        original = service.runners[kind]  # type: ignore[index]

        def gated(ctx: Any) -> None:
            ctx.progress(0.4)
            self.release.wait(20)
            original(ctx)

        service.runners[kind] = gated  # type: ignore[index]


def test_archive_export_with_progress_download_and_delete(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests(instagram="anna.party")
    for _ in range(3):
        g.upload()
    gate = Gate(live, "archive")
    goto(page, live, "/admin/manage?tab=export")
    wait_live(page)
    expect(page.get_by_text("Noch keine Exporte.")).to_be_visible()
    form = page.get_by_test_id("export-archive")
    form.get_by_text("Ausgeblendete Fotos mitnehmen").click()
    form.get_by_role("button", name="Archiv erstellen").click()
    job = page.get_by_test_id("export-job").first
    expect(job).to_have_attribute("data-status", "running")
    expect(job.get_by_role("progressbar", name="Wird erstellt…")).to_have_attribute(
        "aria-valuenow", "40"
    )
    # a second start while it runs gets the same job back
    form.get_by_role("button", name="Archiv erstellen").click()
    expect(toast(page)).to_contain_text("Läuft schon")
    expect(page.get_by_test_id("export-job")).to_have_count(1)
    jobs = live.core.services.exports.jobs()
    assert len(jobs) == 1 and jobs[0].options["include_hidden"] is True

    gate.release.set()
    expect(job).to_have_attribute("data-status", "done", timeout=15_000)
    expect(job).to_contain_text(re.compile(r"archiv-.*\.zip, [\d,]+ (kB|MB)"))
    with page.expect_download() as dl:
        job.get_by_test_id("export-download").click()
    assert re.match(r"archiv-.*\.zip$", dl.value.suggested_filename)
    with zipfile.ZipFile(dl.value.path()) as z:
        assert sum(1 for n in z.namelist() if n.endswith(".jpg")) == 3

    job.get_by_test_id("export-delete").click()
    dialog = confirm_dialog(page)
    expect(dialog).to_contain_text("löschen?")
    expect(dialog.get_by_role("button", name="Abbrechen")).to_be_focused()
    dialog.get_by_role("button", name="Löschen").click()
    expect(page.get_by_test_id("export-job")).to_have_count(0)
    assert live.core.services.exports.jobs() == []
    assert errors(page) == []


def test_qr_sheet_needs_an_address(desktop_page: Page, live: LiveServer) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=export")
    form = page.get_by_test_id("export-qr")
    field = form.get_by_label("Adresse der Party")
    expect(field).to_have_value("")  # no VB_PUBLIC_BASE_URL in this party
    form.get_by_role("button", name="QR-Bogen erstellen").click()
    expect(form).to_contain_text("Bitte die Adresse der Party angeben.")
    field.fill("not a url")
    form.get_by_role("button", name="QR-Bogen erstellen").click()
    expect(form.get_by_text(re.compile("Adresse|URL"))).not_to_have_count(0)
    field.fill("https://party.example.org")
    form.get_by_role("button", name="QR-Bogen erstellen").click()
    job = page.get_by_test_id("export-job").first
    expect(job).to_have_attribute("data-kind", "qr")
    expect(job).to_have_attribute("data-status", "done", timeout=15_000)
    assert errors(page, 400) == []


def test_timelapse_without_ffmpeg_is_explained(
    desktop_page: Page, live: LiveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ExportService, "ffmpeg_available", staticmethod(lambda: False))
    goto(desktop_page, live, "/admin/manage?tab=export")
    form = desktop_page.get_by_test_id("export-timelapse")
    expect(form.get_by_test_id("no-ffmpeg")).to_contain_text("ffmpeg")
    expect(form.get_by_role("button", name="Zeitraffer erstellen")).to_be_disabled()
    assert errors(desktop_page) == []
