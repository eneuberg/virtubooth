"""Verwaltung → Plakat: upload a PDF template, place the green QR field with mouse,
touch and keyboard, save it, switch pages, print a test poster, remove the template.
pdf.js renders under the real CSP (worker from /assets/, no wasm): no console errors.

The template is generated here with Pillow (two pages of different sizes)."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import Locator, Page, expect

from ..conftest import LiveServer, shot
from .conftest import errors, goto, no_horizontal_scroll, toast

pytestmark = pytest.mark.e2e

A4 = (595, 842)
A5_LANDSCAPE = (595, 420)


def template_pdf() -> bytes:
    """Page 1: A4, pink with a white card; page 2: A5 landscape, blue."""
    first = Image.new("RGB", A4, (236, 72, 153))
    ImageDraw.Draw(first).rectangle((150, 400, 445, 695), fill="white")
    second = Image.new("RGB", A5_LANDSCAPE, (59, 130, 246))
    buf = io.BytesIO()
    first.save(buf, "PDF", save_all=True, append_images=[second], resolution=72)
    return buf.getvalue()


def section(page: Page, live: LiveServer) -> None:
    goto(page, live, "/admin/manage?tab=plakat")
    expect(page.get_by_role("heading", name="Plakat", level=1)).to_be_visible()


def canvas(page: Page) -> Locator:
    return page.get_by_test_id("poster-page")


def wait_drawn(page: Page) -> None:
    expect(canvas(page)).to_have_attribute("data-drawn", "true", timeout=20_000)


def ink(page: Page) -> int:
    """Sampled pixels of the drawn page that are not white (0: blank)."""
    count: int = canvas(page).evaluate(
        """(c) => {
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 0; i < d.length; i += 4 * 101) if (d[i] < 235 || d[i + 1] < 235 || d[i + 2] < 235) n++;
            return n;
        }"""
    )
    return count


def field_rect(page: Page) -> dict[str, float]:
    """The green field relative to the drawn page (0..1, origin top left)."""
    page_box = canvas(page).bounding_box()
    box = page.get_by_test_id("qr-field").bounding_box()
    assert page_box and box
    return {
        "x": (box["x"] - page_box["x"]) / page_box["width"],
        "y": (box["y"] - page_box["y"]) / page_box["height"],
        "w": box["width"] / page_box["width"],
        "h": box["height"] / page_box["height"],
    }


def centre(page: Page, test_id: str) -> tuple[float, float]:
    el = page.get_by_test_id(test_id)
    el.evaluate("(el) => el.scrollIntoView({block: 'center', inline: 'center'})")
    box = el.bounding_box()
    assert box
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def close(a: dict[str, float], b: dict[str, Any], tolerance: float = 0.01) -> bool:
    return all(abs(a[k] - float(b[k])) <= tolerance for k in ("x", "y", "w", "h"))


def saved_rect(live: LiveServer) -> dict[str, Any]:
    template = live.core.services.posters.template()
    assert template is not None and template.rect is not None
    return template.rect.model_dump()


def upload_via_input(page: Page, data: bytes, name: str = "vorlage.pdf") -> None:
    page.locator("input[type=file]").first.set_input_files(
        {"name": name, "mimeType": "application/pdf", "buffer": data}
    )


def upload_via_api(page: Page, data: bytes) -> None:
    status = page.evaluate(
        """async (b64) => {
            const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
            const res = await fetch('/api/admin/poster/template', {method: 'PUT',
                headers: {'Content-Type': 'application/pdf'}, body: bytes});
            return res.status;
        }""",
        base64.b64encode(data).decode(),
    )
    assert status == 200


def test_desktop_upload_place_save_switch_print_remove(
    desktop_page: Page, live: LiveServer, tmp_path: Path
) -> None:
    page = desktop_page
    section(page, live)
    expect(page.get_by_text("Noch keine Vorlage")).to_be_visible()

    # a file that only looks like a PDF: the server takes it, pdf.js can't show it
    upload_via_input(page, b"%PDF-1.7\nnot really a pdf\n")
    expect(page.get_by_test_id("poster-error")).to_have_text(
        "Die PDF lässt sich hier nicht anzeigen. Ist sie beschädigt oder mit Passwort geschützt?"
    )
    # replace it with a real one
    upload_via_input(page, template_pdf())
    expect(toast(page)).to_contain_text("Vorlage hochgeladen. Jetzt das grüne Feld platzieren.")
    wait_drawn(page)
    assert ink(page) > 100, "the page was not drawn"
    expect(page.get_by_test_id("poster-state")).to_have_attribute("data-dirty", "true")

    # the default: a centred square of 40 % of the shorter side
    start = field_rect(page)
    assert abs(start["w"] - 0.4) < 0.01 and abs(start["x"] - 0.3) < 0.01
    assert abs(start["h"] * A4[1] - start["w"] * A4[0]) < 0.01 * A4[0]

    # drag it with the mouse
    x, y = centre(page, "qr-field")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 60, y + 40, steps=6)
    page.mouse.up()
    moved = field_rect(page)
    width = canvas(page).bounding_box()["width"]  # type: ignore[index]
    assert abs((moved["x"] - start["x"]) * width + 60) < 3
    assert moved["y"] > start["y"]

    # resize with the corner handle: it stays square
    hx, hy = centre(page, "qr-field-handle")
    page.mouse.move(hx, hy)
    page.mouse.down()
    page.mouse.move(hx + 50, hy + 50, steps=6)
    page.mouse.up()
    grown = field_rect(page)
    assert grown["w"] > moved["w"] + 0.05
    assert abs(grown["x"] - moved["x"]) < 0.002
    assert abs(grown["h"] * A4[1] - grown["w"] * A4[0]) < 0.01 * A4[0]

    page.get_by_test_id("poster-save").click()
    expect(toast(page)).to_contain_text("QR-Feld gespeichert.")
    expect(page.get_by_test_id("poster-state")).to_have_attribute("data-dirty", "false")
    expect(page.get_by_test_id("poster-save")).to_be_disabled()
    assert close(grown, saved_rect(live))
    template = live.core.services.posters.template()
    assert template is not None and template.page == 0 and template.pages == 2
    shot(page, "poster_desktop_saved")

    # after a reload: the same field
    page.reload()
    wait_drawn(page)
    assert close(field_rect(page), saved_rect(live))

    # page 2 (landscape): a new default field, unsaved; back on page 1: the saved one
    page.get_by_test_id("poster-page-select").get_by_role("button").click()
    page.get_by_role("option", name="Seite 2 von 2").click()
    wait_drawn(page)
    box = canvas(page).bounding_box()
    assert box and abs(box["width"] / box["height"] - A5_LANDSCAPE[0] / A5_LANDSCAPE[1]) < 0.02
    expect(page.get_by_test_id("poster-state")).to_have_attribute("data-dirty", "true")
    page.get_by_test_id("poster-discard").click()
    wait_drawn(page)
    assert close(field_rect(page), saved_rect(live))

    # the test print: one PDF page with the sample code
    with page.expect_download() as download:
        page.get_by_test_id("poster-test-print").click()
    assert download.value.suggested_filename == "plakat-00-muster.pdf"
    target = tmp_path / "probe.pdf"
    download.value.save_as(target)
    data = target.read_bytes()
    assert data.startswith(b"%PDF-")

    # remove it: the standard poster again
    page.get_by_test_id("poster-remove").click()
    dialog = page.get_by_role("alertdialog", name="Vorlage entfernen?")
    expect(dialog).to_contain_text("Danach gibt es wieder das Standard-Plakat.")
    dialog.get_by_role("button", name="Entfernen").click()
    expect(toast(page)).to_contain_text("Vorlage entfernt.")
    expect(page.get_by_text("Noch keine Vorlage")).to_be_visible()
    assert live.core.services.posters.template() is None
    shot(page, "poster_desktop_empty")

    # the standard poster as a PDF
    with page.expect_download() as download:
        page.get_by_test_id("poster-standard").click()
    assert download.value.suggested_filename == "plakat-00-muster.pdf"
    assert errors(page) == []


def touch(el: Locator, kind: str, x: float, y: float) -> None:
    el.dispatch_event(
        f"pointer{kind}",
        {
            "pointerId": 7,
            "pointerType": "touch",
            "isPrimary": True,
            "clientX": x,
            "clientY": y,
            "button": 0 if kind == "down" else -1,
            "buttons": 0 if kind == "up" else 1,
            "bubbles": True,
            "cancelable": True,
        },
    )


def touch_drag(page: Page, test_id: str, dx: float, dy: float) -> None:
    el = page.get_by_test_id(test_id)
    x, y = centre(page, test_id)
    touch(el, "down", x, y)
    for i in range(1, 5):
        touch(el, "move", x + dx * i / 4, y + dy * i / 4)
    touch(el, "up", x + dx, y + dy)


def test_phone_touch_and_keyboard(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    goto(page, live, "/admin/manage")
    upload_via_api(page, template_pdf())
    section(page, live)
    wait_drawn(page)
    assert ink(page) > 100
    assert no_horizontal_scroll(page)
    width = canvas(page).bounding_box()["width"]  # type: ignore[index]
    assert width > 300  # the page takes the phone's width
    shot(page, "poster_phone")

    # the square and its handle take touches (touch-action: none), the page scrolls elsewhere
    for test_id in ("qr-field", "qr-field-handle"):
        action = page.get_by_test_id(test_id).evaluate("(el) => getComputedStyle(el).touchAction")
        assert action == "none"
    assert canvas(page).evaluate("(el) => getComputedStyle(el).touchAction") != "none"

    start = field_rect(page)
    touch_drag(page, "qr-field", 40, -30)
    moved = field_rect(page)
    assert abs((moved["x"] - start["x"]) * width - 40) < 3
    assert moved["y"] < start["y"]

    touch_drag(page, "qr-field-handle", -30, -30)
    shrunk = field_rect(page)
    assert shrunk["w"] < moved["w"] - 0.05
    assert abs(shrunk["x"] - moved["x"]) < 0.002

    # the keyboard: arrows 1 % (Shift 5 %), plus 1 %
    field = page.get_by_test_id("qr-field")
    field.focus()
    for key in ("ArrowRight", "ArrowRight", "Shift+ArrowDown", "+"):
        page.keyboard.press(key)
    keyed = field_rect(page)
    assert abs(keyed["w"] - (shrunk["w"] + 0.01)) < 0.003
    # + grows around the centre: x moves left by half a percent
    assert abs(keyed["x"] - (shrunk["x"] + 0.02 - 0.005)) < 0.003
    assert abs(keyed["y"] - (shrunk["y"] + 0.05 - 0.005 * A4[0] / A4[1])) < 0.003
    status = page.get_by_test_id("qr-field-status")
    expect(status).to_contain_text("QR-Feld: links")
    expect(status).to_contain_text(f"Größe {round(keyed['w'] * 100)}")

    page.get_by_test_id("poster-save").click()
    expect(toast(page)).to_contain_text("QR-Feld gespeichert.")
    assert close(keyed, saved_rect(live))
    page.get_by_test_id("poster-actions").evaluate("(el) => el.scrollIntoView({block: 'end'})")
    shot(page, "poster_phone_saved")
    assert no_horizontal_scroll(page)
    assert errors(page) == []
