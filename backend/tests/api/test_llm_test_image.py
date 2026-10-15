"""`POST /test-image` (PLAN-NIGHT §4.4): local pipeline and/or external AI on
an image that is never stored as a photo."""

from __future__ import annotations

import pytest

from virtubooth.extensions.wall.llm import admin_api, ports
from virtubooth.extensions.wall.llm.providers.base import ProviderError

from ..conftest import ORIGIN, jpeg, png
from ..llm_fakes import FakeProvider, setup_llm

URL = "/api/x/wall/admin/test-image"


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def send(client, image=None, *, analyzers="all", external="0", mime="image/jpeg"):
    return client.post(
        URL,
        files={"file": ("test.jpg", image if image is not None else jpeg(800, 600), mime)},
        data={"analyzers": analyzers, "external": external},
        headers=ORIGIN,
    )


def photo_count(core) -> int:
    return core.db.one("SELECT COUNT(*) AS n FROM photos")["n"]


def test_worker_off_is_409(admin):
    r = send(admin)
    assert r.status_code == 409 and r.json()["error"] == "worker_off"


def test_local_run(admin, core, monkeypatch):
    seen = {}

    def submit(core_, image, analyzers, timeout_s=30):
        seen["analyzers"] = analyzers
        seen["image"] = image
        return ports.TestRun(
            width=800,
            height=600,
            facts={"brightness": 0.4},
            boxes=[{"kind": "face", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}],
            details=[],
            objects=[ports.DetectedObject("cup", "Tasse", 0.6, (0.5, 0.5, 0.1, 0.1))],
            durations_ms={"basic": 12},
            error=None,
        )

    monkeypatch.setattr(ports, "submit_test", submit)
    r = send(admin, analyzers="basic,objects")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["width"] == 800 and body["height"] == 600 and body["external"] is None
    assert body["local"]["facts"] == {"brightness": 0.4}
    assert body["local"]["objects"] == [
        {"label": "cup", "label_de": "Tasse", "score": 0.6,
         "box": {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}}
    ]  # fmt: skip
    assert seen["analyzers"] == ["basic", "objects"] and seen["image"][:3] == b"\xff\xd8\xff"
    send(admin)
    assert seen["analyzers"] is None  # "all"
    assert photo_count(core) == 0


def test_unknown_analyzer(admin):
    r = send(admin, analyzers="basic,telepathy")
    assert r.status_code == 400 and r.json()["error"] == "unknown_analyzer"


def test_external_only(admin, core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)  # noqa: F841 - keeps the service alive for the app
    r = send(admin, analyzers="", external="1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["local"] is None
    assert body["external"]["objects"][0]["label_de"] == "Hut"
    assert body["external"]["usage"]["calls"] == 1 and body["external"]["error"] is None
    assert core.db.one("SELECT kind, ok FROM llm_usage")["kind"] == "test"
    assert photo_count(core) == 0
    # a provider failure is reported, not raised
    fake.fail = ProviderError("Die KI hat die Anfrage abgelehnt.", kind="refused")
    body = send(admin, analyzers="", external="1").json()
    assert body["external"]["error"] == "Die KI hat die Anfrage abgelehnt."


def test_external_needs_a_key_and_budget(admin, core):
    r = send(admin, analyzers="", external="1")
    assert r.status_code == 400 and r.json()["error"] == "llm_not_configured"
    svc = setup_llm(  # noqa: F841
        core,
        FakeProvider(),
        budget={"party_usd": None, "party_calls": 0, "daily_usd": None, "daily_calls": None},
    )
    r = send(admin, analyzers="", external="1")
    assert r.status_code == 409 and r.json()["error"] == "llm_budget_exhausted"


def test_validated_like_uploads(admin, core, settings):
    r = send(admin, png(), analyzers="")
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
    r = send(admin, png(), analyzers="", mime="image/png")
    assert r.status_code == 415 and r.json()["error"] == "unsupported_type"
    r = admin.post(URL, content=jpeg(), headers={**ORIGIN, "Content-Type": "image/jpeg"})
    assert r.status_code == 415
    r = send(admin, jpeg(40, 40), analyzers="")
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
    big = b"\xff\xd8\xff" + b"0" * (settings.max_upload_bytes + 1)
    r = send(admin, big, analyzers="")
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    r = admin.post(URL, data={"analyzers": "all"}, files={"x": ("a", b"1")}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "empty_upload"


def test_rate_limit(admin):
    codes = [send(admin, b"x", analyzers="").status_code for _ in range(7)]
    assert codes[:6] == [400] * 6 and codes[6] == 429


def test_admin_only(client):
    assert send(client).status_code == 401
