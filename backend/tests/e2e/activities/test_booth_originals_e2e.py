"""The Fotobox's unfiltered originals end to end: a shot through a strong filter
uploads the photo as shown plus the same frame without the filter; the admin sees
the filtered photo by default, „Filter zeigen“ switches to the original, and an
archive „ohne Filter“ contains the original; the guest's „Deine Bilder“ switches
too."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator

import pytest
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import Browser, BrowserContext, Page, expect

from ..admin.conftest import DESKTOP_VIEWPORT, admin_context, goto, login_api, wait_until
from ..conftest import LiveServer, track_errors
from .conftest import READY, open_booth, photos, select_filter, shoot

pytestmark = pytest.mark.e2e


def diff(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


@pytest.fixture
def open_admin(browser: Browser, live: LiveServer) -> Iterator[Callable[[], Page]]:
    """The admin's page, opened only when asked: a second context opened before the
    shot keeps Firefox's fake camera from the booth."""
    contexts: list[BrowserContext] = []

    def open_() -> Page:
        ctx = admin_context(browser, DESKTOP_VIEWPORT)
        contexts.append(ctx)
        page = track_errors(ctx.new_page())
        login_api(page, live)
        return page

    yield open_
    for ctx in contexts:
        ctx.close()


def test_thermal_shot_keeps_its_original(
    guest: Page, live: LiveServer, open_admin: Callable[[], Page]
):
    page = guest
    open_booth(page, live)
    select_filter(page, "thermal")
    page.wait_for_timeout(300)
    shoot(page)
    [photo] = photos(live, "booth")
    assert photo.raw_filename is not None and photo.meta["filter"] == "thermal"
    repo = live.core.repos.photos
    shown = Image.open(repo.path("booth", photo.filename)).convert("RGB")
    raw = Image.open(repo.path("booth", photo.raw_filename)).convert("RGB")
    assert raw.size == shown.size == (1080, 1440)
    # the heat palette is gone in the original: clearly another picture of the same size
    assert diff(shown, raw) > 15, diff(shown, raw)
    raw_bytes = repo.path("booth", photo.raw_filename).read_bytes()

    # the admin: filtered by default, „Filter zeigen“ shows the original
    admin = open_admin()
    goto(admin, live, f"/admin/manage?photo={photo.public_id}")
    inspector = admin.get_by_test_id("inspector")
    img = inspector.get_by_test_id("inspector-img")
    expect(img).to_have_attribute("data-variant", "filtered")
    expect(img).to_have_attribute("src", f"/media/{photo.public_id}")
    tile = admin.locator(f'[data-photo-id="{photo.public_id}"] img').first
    expect(tile).to_have_attribute("src", f"/media/{photo.public_id}?thumb=1")
    switch = inspector.get_by_role("switch", name="Filter zeigen")
    expect(switch).to_be_checked()
    inspector.get_by_test_id("filter-toggle").click()
    expect(img).to_have_attribute("data-variant", "raw")
    expect(img).to_have_attribute("src", f"/media/{photo.public_id}?variant=raw")
    expect(tile).to_have_attribute("src", f"/media/{photo.public_id}?variant=raw&thumb=1")
    # (polled from here: the CSP forbids wait_for_function's eval in Firefox)
    wait_until(lambda: img.evaluate("el => el.complete && el.naturalWidth === 1080"))
    # both downloads are offered
    expect(inspector.get_by_test_id("download-original")).to_have_attribute(
        "href", f"/media/{photo.public_id}?variant=raw&download=1"
    )
    # remembered in this browser: the Live page shows the original too
    goto(admin, live, "/admin/live")
    expect(admin.locator(f'[data-photo-id="{photo.public_id}"] img').first).to_have_attribute(
        "src", f"/media/{photo.public_id}?variant=raw&thumb=1"
    )
    expect(admin.get_by_role("switch", name="Filter zeigen")).not_to_be_checked()

    # an archive without filters holds the original
    goto(admin, live, "/admin/manage?tab=export")
    form = admin.get_by_test_id("export-archive")
    form.get_by_test_id("export-filters").get_by_text("Ohne Filter", exact=True).click()
    expect(form.get_by_role("radio", name="Ohne Filter")).to_be_checked()
    form.get_by_role("button", name="Archiv erstellen").click()
    job = admin.get_by_test_id("export-job").first
    expect(job).to_have_attribute("data-status", "done", timeout=READY)
    expect(job).to_contain_text("ohne Filter (Originale)")
    with admin.expect_download() as dl:
        job.get_by_test_id("export-download").click()
    with zipfile.ZipFile(dl.value.path()) as z:
        jpgs = [n for n in z.namelist() if n.endswith(".jpg")]
        assert len(jpgs) == 1 and z.read(jpgs[0]) == raw_bytes
    assert admin.js_errors == []

    # the guest's own pictures switch as well
    page.get_by_test_id("again").click()
    page.goto(live.url("/"))
    mine = page.get_by_test_id("my-photos")
    expect(mine).to_have_attribute("data-state", "ready", timeout=READY)
    mine.get_by_test_id(f"photo-{photo.public_id}").click()
    viewer = page.get_by_test_id("photo-viewer-img")
    expect(viewer).to_have_attribute("data-variant", "filtered")
    page.get_by_test_id("photo-filter-switch").click()
    expect(viewer).to_have_attribute("data-variant", "raw")
    expect(viewer).to_have_attribute("src", f"/media/{photo.public_id}?variant=raw")
    assert page.js_errors == []


def test_normal_shot_has_no_second_file(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    select_filter(page, "normal")
    shoot(page)
    [photo] = photos(live, "booth")
    assert photo.raw_filename is None
    assert not (live.core.settings.data_dir / "booth" / "raw").exists()
    # the request carried no original either (one JPEG body)
    assert page.js_errors == []


def test_overlay_only_filter_keeps_an_original(guest: Page, live: LiveServer):
    """The party frame is an overlay over the plain picture: the original has no frame."""
    page = guest
    open_booth(page, live)
    select_filter(page, "party")
    shoot(page)
    [photo] = photos(live, "booth")
    assert photo.raw_filename is not None
    repo = live.core.repos.photos
    shown = Image.open(repo.path("booth", photo.filename)).convert("RGB")
    raw = Image.open(io.BytesIO(repo.path("booth", photo.raw_filename).read_bytes())).convert("RGB")
    # the frame sits at the edges: the borders differ, the middle is the same picture
    edge = (0, 0, 1080, 60)
    middle = (340, 520, 740, 920)
    assert diff(shown.crop(edge), raw.crop(edge)) > diff(shown.crop(middle), raw.crop(middle))
    assert page.js_errors == []
