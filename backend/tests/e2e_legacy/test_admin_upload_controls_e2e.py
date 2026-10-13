"""Upload controls in real browsers: the admin's "Uploads" chip and sheet
(stop all uploads, pause new guests with restore/keep), the per-guest switch
on the user page, and what guests see (the SDK hint, the refused upload).

Set VB_SCREENSHOT_DIR=/some/dir to also save screenshots.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx2 as httpx
import pytest
from playwright.sync_api import Page, expect

from virtubooth.extension import Extension, UploadPolicy
from virtubooth.repo import PhotoQuery

from ..conftest import fp, jpeg
from .conftest import accept_consent_in_browser, new_context, track_errors

pytestmark = pytest.mark.e2e

PAUSED_MSG = "Uploads sind für dich gerade pausiert. Die Gastgeber schalten sie bald wieder frei."
STOPPED_MSG = "Uploads sind gerade kurz gestoppt – gleich geht's weiter."
SINCE = r"seit \d\d:\d\d"

SNAP_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Snap</title>
<link rel="stylesheet" href="/static/core/vb.css">
<script type="module" src="./snap.js"></script></head>
<body><main class="vb-page"><div id="chip"></div><h1>Snap 📷</h1>
<button class="vb-btn vb-btn--primary vb-btn--big" id="go" type="button" data-testid="go" disabled>Hochladen</button>
<p id="out" data-testid="out"></p></main></body></html>
"""

SNAP_JS = """
import { boot, canvasToJpeg, mountUserChip, uploadJpeg } from '/static/core/vb.js';
const out = document.getElementById('out');
const go = document.getElementById('go');
await boot();
mountUserChip(document.getElementById('chip'));
go.addEventListener('click', async () => {
  go.disabled = true;
  out.textContent = '';
  out.removeAttribute('data-state');
  const canvas = document.createElement('canvas');
  canvas.width = 300;
  canvas.height = 400;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#22aa88';
  ctx.fillRect(0, 0, 300, 400);
  try {
    const res = await uploadJpeg('snap', await canvasToJpeg(canvas));
    out.dataset.state = 'ok';
    out.textContent = `Hochgeladen #${res.photo.seq}`;
  } catch (err) {
    out.dataset.state = err.code;
    out.textContent = err.message;
  } finally {
    go.disabled = false;
  }
});
go.disabled = false;
"""


@pytest.fixture
def e2e_extensions(tmp_path: Path):
    static = tmp_path / "snap"
    static.mkdir()
    (static / "index.html").write_text(SNAP_HTML)
    (static / "snap.js").write_text(SNAP_JS)
    return [
        Extension(
            id="snap", title="Schnappschuss", emoji="📷", tagline="Test",
            static_dir=static, upload=UploadPolicy(),
        )  # fmt: skip
    ]


def shot(page: Page, name: str, settle_ms: int = 400) -> None:
    out = os.environ.get("VB_SCREENSHOT_DIR")
    if not out:
        return
    page.wait_for_timeout(settle_ms)
    Path(out).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(Path(out) / f"upload-controls-{name}.png"))


def real_errors(page: Page) -> list[str]:
    # refused uploads (403) are logged as failed resources: that's the point here
    return [e for e in page.js_errors if "Failed to load resource" not in e and "403" not in e]


class ApiGuest:
    """A guest that talks HTTP only (for "everyone else at the party")."""

    def __init__(self, live, fp_n: int) -> None:
        self.live = live
        self.client = httpx.Client(base_url=live.base_url)
        assert self.client.get(live.entry("/")).status_code == 303
        r = self.client.post(
            "/api/join",
            json={"accept": True, "version": "1", "fp": fp(fp_n)},
            headers={"Origin": live.base_url},
        )
        assert r.status_code == 201, r.text
        public_id = live.core.signer.unsign("uid", self.client.cookies.get("vb_uid"))
        self.id = live.core.repo.get_user_by_public_id(public_id).id

    def upload_status(self) -> int:
        r = self.client.post(
            "/api/x/snap/upload",
            content=jpeg(300, 400),
            headers={"Content-Type": "image/jpeg", "Origin": self.live.base_url},
        )
        return r.status_code


@pytest.fixture
def api_guests(live):
    made: list[ApiGuest] = []

    def make(fp_n: int) -> ApiGuest:
        g = ApiGuest(live, fp_n)
        made.append(g)
        return g

    yield make
    for g in made:
        g.client.close()


class BrowserGuest:
    def __init__(self, browser, live) -> None:
        self.context = new_context(browser)
        self.page = track_errors(self.context.new_page())
        self.live = live
        self.page.goto(live.entry("/x/snap/"))
        accept_consent_in_browser(self.page)
        expect(self.page.get_by_test_id("go")).to_be_enabled()
        public_id = live.core.signer.unsign(
            "uid", next(c["value"] for c in self.context.cookies() if c["name"] == "vb_uid")
        )
        self.id = live.core.repo.get_user_by_public_id(public_id).id

    @property
    def hint(self):
        return self.page.get_by_test_id("uploads-paused")

    def upload(self, expected_state: str):
        self.page.get_by_test_id("go").click()
        out = self.page.get_by_test_id("out")
        expect(out).to_have_attribute("data-state", expected_state)
        return out

    def recheck(self) -> None:
        """What happens when the guest comes back to the tab (or every 30 s)."""
        self.page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")


@pytest.fixture
def browser_guests(browser, live):
    made: list[BrowserGuest] = []

    def make() -> BrowserGuest:
        g = BrowserGuest(browser, live)
        made.append(g)
        return g

    yield make
    for g in made:
        g.context.close()


def chip_text(page: Page):
    return page.get_by_test_id("uploads-chip-text")


def open_sheet(page: Page):
    page.get_by_test_id("uploads-chip").click()
    sheet = page.get_by_test_id("uploads-sheet")
    expect(sheet).to_be_visible()
    return sheet


def close_sheet(page: Page) -> None:
    page.get_by_test_id("uploads-close").click()
    expect(page.get_by_test_id("uploads-sheet")).to_have_count(0)


# --------------------------------------------------------- new-guest lock


def test_pause_new_guests_then_restore(admin_page, live, browser_guests, api_guests):
    admin = admin_page
    known = api_guests(1)
    admin.goto(live.url("/admin/live"))
    expect(admin.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    expect(chip_text(admin)).to_have_text("🟢 Uploads laufen")
    shot(admin, "live-ok")

    sheet = open_sheet(admin)
    expect(sheet.get_by_test_id("uploads-status")).to_have_text("🟢 Uploads laufen")
    switch = sheet.get_by_role("switch", name="Neue Gäste pausieren")
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "true")
    expect(sheet.get_by_test_id("upload-pause-state")).to_have_text(
        re.compile(rf"Neue Gäste können {SINCE} nichts hochladen · 0 betroffen")
    )
    close_sheet(admin)
    expect(chip_text(admin)).to_have_text(re.compile(rf"⏸ Neue Gäste pausiert {SINCE} · 0 betroffen"))
    assert live.core.repo.upload_lock()["enabled"]

    # a new guest joins in another browser: hint on the page, upload refused
    guest = browser_guests()
    expect(guest.hint).to_have_text("⏸ Uploads sind gerade pausiert")
    shot(guest.page, "guest-hint")
    guest.hint.click()
    info = guest.page.get_by_test_id("uploads-paused-info")
    expect(info).to_contain_text("Uploads sind für dich pausiert")
    expect(info).to_contain_text("Instagram-Namen")
    shot(guest.page, "guest-hint-info")
    info.get_by_role("button", name="Alles klar").click()
    expect(info).to_have_count(0)
    expect(guest.upload("uploads_paused")).to_have_text(PAUSED_MSG)
    expect(guest.hint).to_be_visible()
    # guests from before keep uploading; the admin's chip counts the new one live
    assert known.upload_status() == 201
    expect(chip_text(admin)).to_have_text(re.compile(r"· 1 betroffen$"))
    shot(admin, "live-paused")

    # end it: restore
    sheet = open_sheet(admin)
    sheet.get_by_role("switch", name="Neue Gäste pausieren").click()
    expect(sheet.get_by_test_id("pause-end-text")).to_contain_text("1 Gast ist beigetreten")
    expect(sheet.get_by_test_id("pause-end-keep")).to_have_text(
        "Nur ab jetzt wieder erlauben – der eine bleibt pausiert"
    )
    shot(admin, "end-pause-dialog")
    restore = sheet.get_by_test_id("pause-end-restore")
    expect(restore).to_have_text("▶ Den 1 in der Pause beigetretenen Gast wieder freischalten")
    restore.click()
    expect(admin.get_by_text("▶ 1 Gast wieder freigeschaltet")).to_be_visible()
    expect(sheet.get_by_test_id("uploads-status")).to_have_text("🟢 Uploads laufen")
    close_sheet(admin)
    expect(chip_text(admin)).to_have_text("🟢 Uploads laufen")
    assert not live.core.repo.get_user(guest.id).uploads_paused

    # the guest can upload now; the hint goes away
    expect(guest.upload("ok")).to_have_text("Hochgeladen #2")
    expect(guest.hint).to_have_count(0)
    assert real_errors(guest.page) == [] and real_errors(admin) == []


def test_pause_new_guests_then_keep(admin_page, live, browser_guests, api_guests):
    admin = admin_page
    admin.goto(live.url("/admin/manage?tab=gaeste"))
    expect(admin.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    sheet = open_sheet(admin)
    sheet.get_by_role("switch", name="Neue Gäste pausieren").click()
    expect(sheet.get_by_test_id("uploads-status")).to_contain_text("⏸ Neue Gäste pausiert")
    close_sheet(admin)

    guest = browser_guests()
    expect(guest.hint).to_be_visible()
    # the guest list shows the badge (live)
    row = admin.locator("[data-testid=guest-row]", has_text=live.core.repo.get_user(guest.id).name)
    expect(row.get_by_test_id("paused-badge")).to_have_text("⏸ Uploads pausiert")
    expect(chip_text(admin)).to_have_text(re.compile(r"· 1 betroffen$"))
    shot(admin, "manage-guests-paused")

    # the user page says why
    row.click()
    admin.wait_for_url(live.url(f"/admin/user?id={guest.id}"))
    panel = admin.get_by_test_id("guest-uploads")
    expect(panel.get_by_test_id("guest-uploads-status")).to_have_text("⏸ Uploads pausiert")
    expect(panel.get_by_test_id("guest-uploads-source")).to_have_text(
        re.compile(rf"automatisch: neue Gäste pausiert {SINCE}")
    )
    admin.go_back()

    # end it: keep paused
    sheet = open_sheet(admin)
    sheet.get_by_role("switch", name="Neue Gäste pausieren").click()
    sheet.get_by_test_id("pause-end-keep").click()
    expect(admin.get_by_text("▶ Neue Gäste können wieder hochladen – 1 bleibt pausiert")).to_be_visible()
    expect(sheet.get_by_test_id("uploads-status")).to_have_text("🟢 Uploads laufen")
    link = sheet.get_by_test_id("uploads-paused-list")
    expect(link).to_have_text("⏸ 1 Gast pausiert · ansehen ›")
    assert live.core.repo.get_user(guest.id).uploads_paused

    expect(guest.upload("uploads_paused")).to_have_text(PAUSED_MSG)
    later = api_guests(2)
    assert later.upload_status() == 201

    # "ansehen" opens the guest list filtered to paused guests
    link.click()
    admin.wait_for_url(re.compile(r"/admin/manage\?tab=gaeste"))
    expect(admin.get_by_role("button", name="⏸ Pausiert")).to_have_attribute("aria-pressed", "true")
    rows = admin.get_by_test_id("guest-row")
    expect(rows).to_have_count(1)
    expect(rows.first.get_by_test_id("paused-badge")).to_be_visible()
    admin.get_by_role("button", name="Alle", exact=True).click()
    expect(rows).to_have_count(2)
    assert real_errors(guest.page) == [] and real_errors(admin) == []


# ---------------------------------------------------------------- one guest


def test_pause_one_guest_from_user_page(admin_page, live, browser_guests):
    admin = admin_page
    guest = browser_guests()
    expect(guest.hint).to_have_count(0)
    expect(guest.upload("ok")).to_have_text("Hochgeladen #1")

    admin.goto(live.url(f"/admin/user?id={guest.id}"))
    panel = admin.get_by_test_id("guest-uploads")
    expect(panel.get_by_test_id("guest-uploads-status")).to_have_text("✓ Darf hochladen")
    panel.get_by_role("button", name="⏸ Uploads pausieren").click()
    expect(panel.get_by_test_id("guest-uploads-status")).to_have_text("⏸ Uploads pausiert")
    expect(panel.get_by_test_id("guest-uploads-source")).to_have_text(re.compile(rf"manuell pausiert · {SINCE}"))
    shot(admin, "user-paused")
    user = live.core.repo.get_user(guest.id)
    assert user.uploads_paused and user.uploads_paused_source == "admin"
    # not a ban: the photo stays visible
    photos = live.core.repo.list_photos(PhotoQuery(user_id=guest.id))
    assert len(photos) == 1 and not photos[0].hidden

    # the guest's page learns it from the refused upload
    expect(guest.upload("uploads_paused")).to_have_text(PAUSED_MSG)
    expect(guest.hint).to_have_text("⏸ Uploads sind gerade pausiert")

    panel.get_by_role("button", name="▶ Uploads erlauben").click()
    expect(panel.get_by_test_id("guest-uploads-status")).to_have_text("✓ Darf hochladen")
    assert not live.core.repo.get_user(guest.id).uploads_paused
    # back on the tab: the hint goes away by itself
    guest.recheck()
    expect(guest.hint).to_have_count(0)
    expect(guest.page.get_by_text("Uploads sind wieder frei 🎉")).to_be_visible()
    expect(guest.upload("ok")).to_have_text("Hochgeladen #2")
    assert real_errors(guest.page) == [] and real_errors(admin) == []


# ------------------------------------------------------------- stop all


def test_stop_all_uploads_and_back(admin_page, context, live, browser_guests, api_guests):
    admin = admin_page
    guest = browser_guests()
    paused = api_guests(2)
    repo = live.core.repo
    repo.set_uploads_paused(paused.id, True, "pytest")
    repo.start_upload_lock("pytest")
    lock = repo.upload_lock()

    admin.goto(live.url("/admin/manage"))
    second = track_errors(context.new_page())  # another admin screen
    second.goto(live.url("/admin/live"))
    for p in (admin, second):
        expect(p.get_by_test_id("conn")).to_have_attribute("data-state", "live")
        expect(chip_text(p)).to_have_text(re.compile(rf"⏸ Neue Gäste pausiert {SINCE} · 0 betroffen"))

    sheet = open_sheet(admin)
    stop = sheet.get_by_role("switch", name="Alle Uploads stoppen")
    stop.click()
    expect(stop).to_have_attribute("aria-checked", "true")
    expect(sheet.get_by_test_id("upload-stop-state")).to_have_text(re.compile(rf"Gestoppt {SINCE}"))
    expect(sheet.get_by_test_id("uploads-status")).to_have_text(
        re.compile(rf"⏹ Alle Uploads gestoppt {SINCE} · ⏸ neue Gäste pausiert")
    )
    shot(admin, "sheet-stopped")
    close_sheet(admin)
    # every admin screen shows it right away
    expect(chip_text(second)).to_have_text(re.compile(rf"⏹ Alle Uploads gestoppt {SINCE}"))
    shot(second, "live-stopped")

    expect(guest.upload("uploads_stopped")).to_have_text(STOPPED_MSG)
    expect(guest.hint).to_have_text("⏹ Uploads kurz gestoppt")
    # a fresh page load knows it from the start
    guest.page.reload()
    expect(guest.hint).to_have_text("⏹ Uploads kurz gestoppt")
    shot(guest.page, "guest-stopped")
    assert paused.upload_status() == 403

    sheet = open_sheet(admin)
    sheet.get_by_role("switch", name="Alle Uploads stoppen").click()
    expect(sheet.get_by_role("switch", name="Alle Uploads stoppen")).to_have_attribute("aria-checked", "false")
    close_sheet(admin)
    expect(chip_text(second)).to_have_text(re.compile(rf"⏸ Neue Gäste pausiert {SINCE} · 0 betroffen"))
    # back to exactly as before: the paused guest and the lock are untouched
    assert repo.get_user(paused.id).uploads_paused
    assert repo.upload_lock() == lock
    assert paused.upload_status() == 403

    guest.recheck()
    expect(guest.hint).to_have_count(0)
    expect(guest.upload("ok")).to_have_text("Hochgeladen #1")
    assert real_errors(guest.page) == [] and real_errors(admin) == [] and real_errors(second) == []
