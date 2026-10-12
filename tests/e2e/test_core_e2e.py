"""Core flows in a real browser: gate, consent, home, camera, upload."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from virtubooth.extension import Extension, UploadPolicy
from virtubooth.repo import PhotoQuery

from .conftest import accept_consent_in_browser

pytestmark = pytest.mark.e2e

PROBE_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/core/vb.css">
<script type="module" src="./probe.js"></script></head>
<body><div class="vb-stage"><video id="v"></video></div><div id="out"></div></body></html>
"""

PROBE_JS = """
import { boot, openCamera, captureFrame, canvasToJpeg, uploadJpeg } from '/static/core/vb.js';
const out = document.getElementById('out');
await boot();
const cam = await openCamera(document.getElementById('v'), { facing: 'environment' });
const canvas = captureFrame(cam.video, 1080, 1440);
const blob = await canvasToJpeg(canvas, 0.85);
const res = await uploadJpeg('probe', blob, { meta: { kind: 'test' } });
out.dataset.seq = res.photo.seq;
out.textContent = 'done';
"""


@pytest.fixture
def e2e_extensions(tmp_path: Path):
    static = tmp_path / "probe"
    static.mkdir()
    (static / "index.html").write_text(PROBE_HTML)
    (static / "probe.js").write_text(PROBE_JS)
    return [
        Extension(
            id="probe",
            title="Probe",
            emoji="🧪",
            tagline="Kamera-Test",
            static_dir=static,
            upload=UploadPolicy(meta_keys=frozenset({"kind"})),
        )
    ]


def test_gate_without_token(page, live):
    page.goto(live.url("/"))
    assert page.get_by_test_id("gate").is_visible()
    assert "Scan den QR-Code" in page.content()


def test_consent_then_home(page, live):
    page.goto(live.entry("/"))
    assert page.url == live.url("/")  # token stripped from the address bar
    accept_consent_in_browser(page, instagram="@e2e.guest")
    page.get_by_test_id("tile-probe").wait_for()
    assert "e2e.guest" in page.get_by_test_id("user-chip").inner_text()
    users = live.core.repo.list_users()
    assert len(users) == 1 and users[0].instagram == "e2e.guest"
    assert users[0].fp_hash and len(users[0].fp_hash) == 64
    # second visit: no banner, same user
    page.reload()
    page.get_by_test_id("tile-probe").wait_for()
    assert page.get_by_test_id("consent").count() == 0
    assert len(live.core.repo.list_users()) == 1
    assert page.js_errors == []


def test_camera_capture_upload(guest_page, live):
    guest_page.goto(live.url("/x/probe/"))
    expect(guest_page.locator("#out")).to_have_text("done", timeout=15000)
    photos = live.core.repo.list_photos(PhotoQuery(extension="probe"))
    assert len(photos) == 1
    assert (photos[0].width, photos[0].height) == (1080, 1440)
    assert photos[0].meta == {"kind": "test"}
    assert guest_page.js_errors == []


def test_edit_instagram_from_chip(guest_page, live):
    guest_page.get_by_test_id("user-chip").click()
    guest_page.fill("#vb-insta-edit", "@new.name")
    guest_page.get_by_role("button", name="Speichern").click()
    expect(guest_page.get_by_test_id("user-chip")).to_contain_text("new.name")
    assert live.core.repo.list_users()[0].instagram == "new.name"


def test_blocked_device_module_does_not_break_the_page(page, live):
    """Content blockers drop URLs that look like tracking. An optional module
    failing must not stop the page; consent still works with a coarse fallback."""
    page.route("**/static/core/device.js", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    page.get_by_test_id("tile-probe").wait_for()
    user = live.core.repo.list_users()[0]
    assert user.fp_components.get("fallback") is True and len(user.fp_hash) == 64


def test_blocked_sdk_shows_a_hint_instead_of_nothing(page, live):
    page.route("**/static/core/vb.js", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    expect(page.get_by_test_id("load-failed")).to_be_visible(timeout=10000)
    expect(page.get_by_test_id("load-failed")).to_contain_text("Blocker")


def test_static_file_names_avoid_blocker_keywords():
    """Filter lists block paths with words like these; keep served files neutral."""
    import re

    from virtubooth.pages import STATIC_DIR

    bad = re.compile(r"fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|ads?[-_./]", re.I)
    roots = [STATIC_DIR, STATIC_DIR.parent / "admin" / "static", STATIC_DIR.parent / "extensions"]
    served = [f for root in roots for f in root.rglob("*") if f.is_file() and f.suffix in {".js", ".css", ".html", ".json", ".svg"}]
    assert served
    offenders = [str(f) for f in served if bad.search(f.name)]
    assert offenders == []
