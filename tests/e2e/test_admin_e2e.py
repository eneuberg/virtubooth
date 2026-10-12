"""Admin screens in a real browser: login, live screen (SSE), management,
user page with ban/unban, event stream."""

from __future__ import annotations

import queue
import re
import threading
from pathlib import Path

import httpx2 as httpx
import pytest
from playwright.sync_api import Page, expect

from virtubooth.admin import api as admin_api
from virtubooth.extension import Extension, UploadPolicy
from virtubooth.ratelimit import RateLimiter

from ..conftest import ADMIN_PASSWORD, fp, jpeg
from .conftest import allow_clipboard, needs_clipboard

pytestmark = pytest.mark.e2e

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
def e2e_extensions(tmp_path: Path):
    static = tmp_path / "snap"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>snap</title>")
    return [
        Extension(
            id="snap",
            title="Schnappschuss",
            emoji="📷",
            tagline="Test",
            static_dir=static,
            upload=UploadPolicy(meta_keys=frozenset({"mood"})),
            meta_labels={"mood": "Laune"},
        )
    ]


class Guest:
    """A party guest talking to the live server over HTTP."""

    def __init__(self, live, *, instagram: str | None = None, fp_n: int = 1) -> None:
        self.live = live
        self.client = httpx.Client(base_url=live.base_url, headers={"User-Agent": IPHONE})
        r = self.client.get(live.entry("/"))
        assert r.status_code == 303, r.text
        r = self.client.post(
            "/api/join",
            json={"accept": True, "version": "1", "instagram": instagram, "fp": fp(fp_n)},
            headers={"Origin": live.base_url},
        )
        assert r.status_code in (200, 201), r.text
        self.state = r.json()["state"]

    def upload_response(self) -> httpx.Response:
        return self.client.post(
            "/api/x/snap/upload",
            content=jpeg(800, 1000, (40, 160, 220)),
            headers={"Content-Type": "image/jpeg", "Origin": self.live.base_url},
        )

    def upload(self) -> str:
        r = self.upload_response()
        assert r.status_code == 201, r.text
        return r.json()["photo"]["id"]

    @property
    def user(self):
        return next(u for u in self.live.core.repo.list_users() if u.public_id == self._public_id())

    def _public_id(self) -> str:
        signed = self.client.cookies.get("vb_uid")
        return self.live.core.signer.unsign("uid", signed)


@pytest.fixture
def guests(live):
    made: list[Guest] = []

    def make(**kwargs) -> Guest:
        g = Guest(live, **kwargs)
        made.append(g)
        return g

    yield make
    for g in made:
        g.client.close()


def track_errors(page: Page) -> Page:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: errors.append(f"{msg.text} @ {msg.location.get('url', '')}") if msg.type == "error" else None)
    page.js_errors = errors  # type: ignore[attr-defined]
    return page


@pytest.fixture
def admin_page(admin_page: Page) -> Page:
    """core's admin_page (phone size, logged in) + console error tracking"""
    return track_errors(admin_page)


def card(page: Page, photo_id: str):
    return page.locator(f'[data-photo-id="{photo_id}"]')


def real_errors(page: Page) -> list[str]:
    # failed requests we caused on purpose (401 on a wrong password) are logged too
    return [e for e in page.js_errors if "Failed to load resource" not in e]


def login_api(page: Page, live) -> None:
    page.goto(live.url("/admin/login"))
    status = page.evaluate(
        """async (pw) => (await fetch('/api/admin/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pw})})).status""",
        ADMIN_PASSWORD,
    )
    assert status == 200


@pytest.fixture
def desktop_page(browser, live):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    p = track_errors(ctx.new_page())
    login_api(p, live)
    yield p
    ctx.close()


def no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


# ------------------------------------------------------------------- login


def test_login_via_ui(page, live):
    page.goto(live.url("/admin/manage"))
    assert page.url == live.url("/admin/login?next=/admin/manage")
    page.fill("#password", "definitely-wrong-password")
    page.get_by_role("button", name="Anmelden").click()
    expect(page.get_by_test_id("login-error")).to_have_text("Falsches Passwort.")
    assert page.url.startswith(live.url("/admin/login"))
    page.fill("#password", ADMIN_PASSWORD)
    page.get_by_role("button", name="Anmelden").click()
    page.wait_for_url(live.url("/admin/manage"))
    expect(page.get_by_role("tab", name="📸 Fotos")).to_have_attribute("aria-selected", "true")
    # logged in already: the login page forwards right away
    page.goto(live.url("/admin/login?next=/admin/live"))
    page.wait_for_url(live.url("/admin/live"))
    assert real_errors(page) == []


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.example/",
        "//evil.example/admin/live",
        "/admin/../x",
        "/admin/Live",
        "javascript:alert(1)",
    ],
)
def test_login_never_redirects_off_site(page, live, next_url):
    page.goto(live.url("/admin/login?next=") + next_url.replace("&", "%26"))
    page.fill("#password", ADMIN_PASSWORD)
    page.get_by_role("button", name="Anmelden").click()
    page.wait_for_url(live.url("/admin/live"))


def test_login_returns_to_user_page_with_id(page, live):
    page.goto(live.url("/admin/user?id=1"))
    assert page.url == live.url("/admin/login?next=/admin/user%3Fid%3D1")
    page.fill("#password", ADMIN_PASSWORD)
    page.get_by_role("button", name="Anmelden").click()
    page.wait_for_url(live.url("/admin/user?id=1"))


def test_login_rate_limit_message(page, live):
    page.goto(live.url("/admin/login"))
    for _ in range(5):
        page.fill("#password", "wrong-password-xyz")
        page.get_by_role("button", name="Anmelden").click()
        expect(page.get_by_test_id("login-error")).to_have_text("Falsches Passwort.")
        page.get_by_test_id("login-error").evaluate("el => { el.textContent = ''; }")
    page.fill("#password", ADMIN_PASSWORD)
    page.get_by_role("button", name="Anmelden").click()
    expect(page.get_by_test_id("login-error")).to_contain_text("Zu viele Anfragen")


def test_logout(admin_page, live):
    admin_page.goto(live.url("/admin/live"))
    admin_page.get_by_role("button", name="Abmelden").click()
    admin_page.wait_for_url(live.url("/admin/login"))
    admin_page.goto(live.url("/admin/live"))
    assert admin_page.url.startswith(live.url("/admin/login?next=/admin/live"))


# -------------------------------------------------------------------- live


def test_live_screen_realtime_and_take_down(admin_page, live, guests):
    page = admin_page
    anna = guests(instagram="anna.party")
    first = anna.upload()
    page.goto(live.url("/admin/live"))
    expect(card(page, first)).to_be_visible()
    expect(page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    expect(page.get_by_test_id("stat-photos")).to_have_text("1")
    expect(page.get_by_test_id("stat-guests")).to_have_text("1")

    # an upload AFTER the page loaded arrives via SSE, on top
    second = anna.upload()
    expect(card(page, second)).to_be_visible(timeout=4000)
    assert page.locator("[data-testid=photo-card]").first.get_attribute("data-photo-id") == second
    expect(page.get_by_test_id("stat-photos")).to_have_text("2")
    c = card(page, second)
    expect(c).to_contain_text("📷 Schnappschuss #2")
    expect(c).to_contain_text("@anna.party")
    expect(c.get_by_test_id("user-link")).to_have_attribute(
        "href", f"/admin/user?id={anna.user.id}"
    )
    expect(c.get_by_test_id("status")).to_have_text("✓ Sichtbar")

    # take it down
    c.get_by_role("button", name="🙈 Runternehmen").click()
    expect(card(page, second).get_by_test_id("status")).to_have_text("🙈 Versteckt")
    expect(card(page, second)).to_have_class(re.compile(r"\bis-hidden\b"))
    assert live.core.repo.get_photo(second).hidden
    expect(page.get_by_test_id("stat-hidden")).to_have_text("1")
    # and back
    card(page, second).get_by_role("button", name="👁 Wieder zeigen").click()
    expect(card(page, second).get_by_test_id("status")).to_have_text("✓ Sichtbar")
    assert not live.core.repo.get_photo(second).hidden

    # the live screen can never delete: not on cards, not in the lightbox
    assert page.get_by_text("Löschen").count() == 0
    assert page.locator("[data-testid*=delete]").count() == 0
    card(page, first).get_by_test_id("thumb").click()
    lightbox = page.get_by_test_id("lightbox")
    expect(lightbox).to_be_visible()
    expect(lightbox).to_contain_text("Schnappschuss #1")
    assert lightbox.get_by_text("Löschen").count() == 0
    lightbox.get_by_role("button", name="🙈 Runternehmen").click()
    expect(lightbox).to_contain_text("Versteckt")
    assert live.core.repo.get_photo(first).hidden
    page.get_by_test_id("lightbox-close").click()
    expect(lightbox).to_have_count(0)
    assert no_horizontal_scroll(page)
    assert page.js_errors == []


def test_live_screens_stay_in_sync(admin_page, context, live, guests):
    g = guests()
    pid = g.upload()
    other = g.upload()
    admin_page.goto(live.url("/admin/live"))
    second = track_errors(context.new_page())
    second.goto(live.url("/admin/live"))
    for p in (admin_page, second):
        expect(p.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    card(admin_page, pid).get_by_role("button", name="🙈 Runternehmen").click()
    expect(card(second, pid).get_by_test_id("status")).to_have_text("🙈 Versteckt")
    # a deletion in the management screen disappears from the live screen
    r = second.evaluate(
        """async (id) => (await fetch('/api/admin/photos/' + id, {method: 'DELETE'})).status""",
        other,
    )
    assert r == 200
    expect(card(admin_page, other)).to_have_count(0)
    assert admin_page.js_errors == [] and second.js_errors == []


def test_live_falls_back_to_polling(admin_page, live, guests):
    page = admin_page
    page.route("**/api/admin/events", lambda route: route.abort())
    g = guests()
    page.goto(live.url("/admin/live"))
    expect(page.get_by_test_id("empty")).to_be_visible()
    expect(page.get_by_test_id("conn")).to_have_attribute("data-state", "reconnecting")
    pid = g.upload()
    expect(card(page, pid)).to_be_visible(timeout=12000)


def test_user_link_opens_user_page(admin_page, live, guests):
    g = guests(instagram="clara.k")
    pid = g.upload()
    admin_page.goto(live.url("/admin/live"))
    card(admin_page, pid).get_by_test_id("user-link").click()
    admin_page.wait_for_url(live.url(f"/admin/user?id={g.user.id}"))
    expect(admin_page.get_by_test_id("user-name")).to_have_text(f"🙂 {g.user.name}")
    expect(admin_page.get_by_test_id("user-insta")).to_have_text("@clara.k")
    expect(card(admin_page, pid)).to_be_visible()
    assert admin_page.js_errors == []


# ------------------------------------------------------------------ manage


def test_manage_delete_needs_confirmation(desktop_page, live, guests):
    page = desktop_page
    g = guests(instagram="ben_b")
    keep, doomed = g.upload(), g.upload()
    doomed_photo = live.core.repo.get_photo(doomed)
    files = [
        live.core.repo.photo_path(doomed_photo.extension, doomed_photo.filename),
        live.core.repo.photo_path(doomed_photo.extension, doomed_photo.thumb_filename),
    ]
    page.goto(live.url("/admin/manage"))
    expect(page.get_by_test_id("photo-total")).to_have_text("2 Fotos")
    tile = card(page, doomed)
    tile.get_by_test_id("delete").click()
    dialog = page.get_by_test_id("confirm")
    expect(dialog).to_contain_text("endgültig löschen?")
    page.get_by_test_id("confirm-cancel").click()
    expect(dialog).to_have_count(0)
    assert live.core.repo.get_photo(doomed) is not None

    tile.get_by_test_id("delete").click()
    page.get_by_test_id("confirm-ok").click()
    expect(card(page, doomed)).to_have_count(0)
    expect(page.get_by_test_id("photo-total")).to_have_text("1 Foto")
    assert live.core.repo.get_photo(doomed) is None
    assert not any(f.exists() for f in files)
    assert live.core.repo.get_photo(keep) is not None
    assert no_horizontal_scroll(page)
    assert page.js_errors == []


def test_manage_bulk_and_filters(desktop_page, live, guests):
    page = desktop_page
    a = guests(instagram="anna")
    b = guests(fp_n=2)
    a1, a2, b1 = a.upload(), a.upload(), b.upload()
    page.goto(live.url("/admin/manage"))
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(3)
    # newest first: b1, a2, a1. Select b1, shift-click a2: both, not a1
    card(page, b1).get_by_test_id("select").click()
    card(page, a2).get_by_test_id("select").click(modifiers=["Shift"])
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-hide").click()
    expect(page.get_by_test_id("bulkbar")).to_be_hidden()
    expect(card(page, b1).get_by_test_id("status")).to_have_text("🙈 Versteckt")
    assert live.core.repo.get_photo(b1).hidden and live.core.repo.get_photo(a2).hidden
    assert not live.core.repo.get_photo(a1).hidden

    # filter: hidden only
    page.get_by_test_id("filter-status").get_by_role("button", name="Versteckt").click()
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(2)
    assert "status=hidden" in page.url
    # filter: one guest
    page.get_by_test_id("filter-user").select_option(str(a.user.id))
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(1)
    expect(card(page, a2)).to_be_visible()
    page.get_by_test_id("filter-status").get_by_role("button", name="Alle").click()
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(2)

    # bulk delete with confirmation; cancelling keeps the selection
    page.get_by_test_id("select-all").click()
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-delete").click()
    page.get_by_test_id("confirm-cancel").click()
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-delete").click()
    expect(page.get_by_test_id("confirm")).to_contain_text("2 Fotos endgültig löschen?")
    page.get_by_test_id("confirm-ok").click()
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(0)
    assert live.core.repo.get_photo(a1) is None and live.core.repo.get_photo(a2) is None
    assert live.core.repo.get_photo(b1) is not None
    assert page.js_errors == []


@needs_clipboard
def test_manage_lightbox_download_and_copy(desktop_page, live, guests):
    page = desktop_page
    allow_clipboard(page.context)
    g = guests(instagram="dj.dennis")
    pid = g.upload()
    page.goto(live.url("/admin/manage"))
    card(page, pid).get_by_test_id("thumb").click()
    lightbox = page.get_by_test_id("lightbox")
    expect(lightbox).to_be_visible()
    expect(lightbox.get_by_test_id("download")).to_have_attribute(
        "href", f"/media/{pid}?download=1"
    )
    lightbox.get_by_test_id("copy-handle").click()
    expect(page.locator(".vb-toast")).to_contain_text("Kopiert: @dj.dennis")
    assert page.evaluate("() => navigator.clipboard.readText()") == "@dj.dennis"
    with page.expect_download() as dl:
        lightbox.get_by_test_id("download").click()
    assert dl.value.suggested_filename == "snap-00001.jpg"
    page.keyboard.press("Escape")
    expect(lightbox).to_have_count(0)
    assert page.js_errors == []


@needs_clipboard
def test_manage_tabs(desktop_page, live, guests):
    page = desktop_page
    allow_clipboard(page.context)
    anna = guests(instagram="anna")
    guests(instagram="ben", fp_n=2).upload()
    anna.upload()
    live.core.repo.ban_user(anna.user.id, "zu wild", "pytest")
    live.core.repo.ban_fingerprint(fp(1)["hash"], "zu wild", "pytest", anna.user.id)
    page.goto(live.url("/admin/manage?tab=gaeste"))
    expect(page.locator("[data-testid=guest-row]")).to_have_count(2)
    page.get_by_test_id("guest-search").fill("ben")
    expect(page.locator("[data-testid=guest-row]")).to_have_count(1)

    page.get_by_role("tab", name="📷 Instagram").click()
    expect(page.locator("[data-testid=insta-row]")).to_have_count(2)
    page.get_by_test_id("copy-all-handles").click()
    # banned guests are left out when copying all handles
    assert page.evaluate("() => navigator.clipboard.readText()") == "@ben"

    page.get_by_role("tab", name="🚫 Sperren").click()
    expect(page.locator("[data-testid=banned-user-row]")).to_have_count(1)
    expect(page.locator("[data-testid=fp-ban-row]")).to_have_count(1)
    page.get_by_test_id("unban-fp").click()
    expect(page.locator("[data-testid=fp-ban-row]")).to_have_count(0)
    assert live.core.repo.list_fingerprint_bans() == []
    page.get_by_test_id("unban-user").click()
    expect(page.locator("[data-testid=banned-user-row]")).to_have_count(0)
    assert not live.core.repo.get_user(anna.user.id).banned

    page.get_by_role("tab", name="📜 Protokoll").click()
    expect(page.get_by_test_id("audit")).to_contain_text("Gast entsperrt")
    expect(page.get_by_test_id("audit")).to_contain_text("Fingerprint entsperrt")
    assert page.js_errors == []


# -------------------------------------------------------------------- user


def test_user_page_ban_and_unban(desktop_page, live, guests):
    page = desktop_page
    g = guests(instagram="troll")
    twin = guests(fp_n=1)  # same phone model: same fingerprint
    p1, p2 = g.upload(), g.upload()
    user = g.user
    page.goto(live.url(f"/admin/user?id={user.id}"))
    expect(page.get_by_test_id("user-status")).to_have_text("✓ Aktiv")
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(2)
    expect(page.get_by_test_id("device")).to_contain_text("iPhone · iOS 18.5 · Safari 18.5")
    expect(page.get_by_test_id("fp-shared")).to_have_text(
        "1 anderes Gerät teilt diesen Fingerprint:"
    )
    expect(page.get_by_test_id("fingerprints").get_by_role("link")).to_have_attribute(
        "href", f"/admin/user?id={twin.user.id}"
    )
    expect(page.get_by_test_id("fp-warning")).to_contain_text("gleiche Handymodelle")

    page.get_by_test_id("ban-reason").fill("Spam")
    page.get_by_test_id("ban-fp").check()
    page.get_by_test_id("ban").click()
    expect(page.get_by_test_id("confirm")).to_contain_text(
        "Zusätzlich wird der Fingerprint gesperrt."
    )
    page.get_by_test_id("confirm-ok").click()
    expect(page.get_by_test_id("user-status")).to_have_text("🚫 GESPERRT")
    expect(page.get_by_test_id("ban-panel")).to_contain_text("Spam")
    for pid in (p1, p2):
        expect(card(page, pid).get_by_test_id("status")).to_have_text("🙈 Versteckt (Sperre)")
        assert live.core.repo.get_photo(pid).hidden_reason == "ban"
    assert live.core.repo.get_user(user.id).ban_reason == "Spam"
    assert [b["fp_hash"] for b in live.core.repo.list_fingerprint_bans()] == [fp(1)["hash"]]
    assert g.upload_response().status_code == 403
    assert twin.upload_response().status_code == 201  # known guests are not hit by the fp ban
    assert guests(fp_n=1).state == "banned"  # a new identity on that fingerprint is

    page.get_by_test_id("unban-fp").check()
    page.get_by_test_id("unban").click()
    expect(page.get_by_test_id("user-status")).to_have_text("✓ Aktiv")
    for pid in (p1, p2):
        expect(card(page, pid).get_by_test_id("status")).to_have_text("✓ Sichtbar")
    assert not live.core.repo.get_user(user.id).banned
    assert live.core.repo.list_fingerprint_bans() == []
    assert g.upload_response().status_code == 201
    assert no_horizontal_scroll(page)
    assert page.js_errors == []


def test_user_page_on_phone(admin_page, live, guests):
    g = guests(instagram="phone.user")
    pid = g.upload()
    admin_page.goto(live.url(f"/admin/user?id={g.user.id}"))
    expect(card(admin_page, pid)).to_be_visible()
    card(admin_page, pid).get_by_test_id("delete").click()
    admin_page.get_by_test_id("confirm-ok").click()
    expect(card(admin_page, pid)).to_have_count(0)
    assert live.core.repo.get_photo(pid) is None
    assert no_horizontal_scroll(admin_page)
    assert admin_page.js_errors == []


def test_user_page_unknown_user(admin_page, live):
    admin_page.goto(live.url("/admin/user?id=999"))
    expect(admin_page.get_by_text("Gast nicht gefunden.")).to_be_visible()
    admin_page.goto(live.url("/admin/user?id=abc"))
    expect(admin_page.get_by_text("Kein Gast ausgewählt.")).to_be_visible()


def test_pages_on_phone_have_no_sideways_scroll(admin_page, live, guests):
    g = guests(instagram="a.very.long.handle.for_layout1")
    g.upload()
    pages = {
        "/admin/live": "photo-card",
        "/admin/manage": "photo-tile",
        "/admin/manage?tab=gaeste": "guest-row",
        "/admin/manage?tab=instagram": "insta-row",
        f"/admin/user?id={g.user.id}": "fingerprints",
    }
    for path, testid in pages.items():
        admin_page.goto(live.url(path))
        expect(admin_page.get_by_test_id(testid).first).to_be_visible()
        expect(admin_page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
        assert no_horizontal_scroll(admin_page), path
    assert admin_page.js_errors == []


# ---------------------------------------------------------------- event API


def _read_events(response, out: queue.Queue) -> None:
    try:
        for line in response.iter_lines():
            out.put(line)
    except httpx.HTTPError:
        pass
    out.put(None)  # stream ended


def _wait_for(out: queue.Queue, predicate, timeout: float = 5.0):
    while True:
        line = out.get(timeout=timeout)
        if line is None or predicate(line):
            return line


def test_event_stream(live, guests, monkeypatch):
    monkeypatch.setattr(admin_api, "SESSION_RECHECK_SECONDS", 0.0)
    g = guests()
    pid = g.upload()
    origin = {"Origin": live.base_url}
    with httpx.Client(base_url=live.base_url, timeout=10) as admin:
        assert admin.get("/api/admin/events").status_code == 401
        admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=origin)
        out: queue.Queue = queue.Queue()
        with admin.stream("GET", "/api/admin/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            t = threading.Thread(target=_read_events, args=(response, out), daemon=True)
            t.start()
            assert _wait_for(out, lambda line: line.startswith("retry:"))
            with httpx.Client(base_url=live.base_url) as other:
                other.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=origin)
                other.post(f"/api/admin/photos/{pid}/hide", headers=origin)
                assert _wait_for(out, lambda line: line == "event: photo.hidden")
                data = _wait_for(out, lambda line: line.startswith("data:"))
                assert pid in data and '"hidden": true' in data
                # once this session logs out, the next event ends its stream
                admin.post("/api/admin/logout", headers=origin)
                other.post(f"/api/admin/photos/{pid}/unhide", headers=origin)
                assert _wait_for(out, lambda line: False) is None
            t.join(5)


def test_back_button_closes_lightbox(admin_page, live, guests):
    page = admin_page
    pid = guests().upload()
    page.goto(live.url("/admin/live"))
    card(page, pid).get_by_test_id("thumb").click()
    expect(page.get_by_test_id("lightbox")).to_be_visible()
    page.go_back()
    expect(page.get_by_test_id("lightbox")).to_have_count(0)
    assert page.url == live.url("/admin/live")
    expect(card(page, pid)).to_be_visible()
    assert page.js_errors == []


def scroll_to_bottom(page: Page) -> None:
    # not mouse.wheel(): Firefox scrolls a capped amount per event, mobile WebKit has no wheel
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")


def test_infinite_scroll_loads_older_photos(admin_page, desktop_page, live, guests):
    live.core.limits.upload_user = RateLimiter(1000, 60)
    g = guests()
    ids = [g.upload() for _ in range(55)]
    page = admin_page
    page.goto(live.url("/admin/live"))
    cards = page.locator("[data-testid=photo-card]")
    expect(cards).to_have_count(30)  # first page
    scroll_to_bottom(page)
    expect(cards).to_have_count(55)
    assert cards.last.get_attribute("data-photo-id") == ids[0]  # oldest at the bottom

    desktop_page.goto(live.url("/admin/manage"))
    tiles = desktop_page.locator("[data-testid=photo-tile]")
    expect(tiles).to_have_count(48)
    scroll_to_bottom(desktop_page)
    expect(tiles).to_have_count(55)
    expect(desktop_page.get_by_test_id("photo-total")).to_have_text("55 Fotos")
    assert page.js_errors == [] and desktop_page.js_errors == []
