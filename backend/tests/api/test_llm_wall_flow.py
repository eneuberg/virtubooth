"""The external-AI path end to end on a real server (INT2): a fake provider,
the admin's property and verdict category through the API, the poller and the
detector threads, `property_scores` and `wall_category_verdicts`, the hub's
`categories.changed`, and the wall screen showing the verdict text.

The fake records every provider call: guests with either opt-out (and banned
or hidden photos) must never appear in any outbound payload."""

from __future__ import annotations

import json
from typing import Any

import pytest

from virtubooth.extensions.wall import hub as hub_module
from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.llm import ports

from ..llm_fakes import (
    COOLEST_SPEC,
    FakeProvider,
    add_guest,
    add_photo,
    set_flags,
    setup_llm,
)
from .wall_support import (
    FakeEnrichment,
    Stream,
    live_admin,
    live_server,
    live_wall,
    wait_until,
    with_wall_page,
)

LLM = "/api/x/wall/admin/llm"
CATEGORIES = "/api/x/wall/admin/categories"


@pytest.fixture
def extensions(demo_extension):
    return [demo_extension, make_extension(enrichment=FakeEnrichment())]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


@pytest.fixture
def live(app, monkeypatch):
    monkeypatch.setattr(hub_module, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(hub_module, "CATEGORIES_DEBOUNCE_SECONDS", 0.2)
    with live_server(app) as server:
        yield server


def _poll_done(core, after: int) -> int | None:
    row = core.db.one("SELECT id, state FROM llm_polls WHERE id > ? ORDER BY id DESC", (after,))
    if row is None or row["state"] == "running":
        return None
    assert row["state"] == "done", dict(row)
    return int(row["id"])


def _outbound(fake: FakeProvider) -> str:
    """Everything the fake was sent as text (names, refs, labels, prompts)."""
    parts: list[Any] = []
    for prompt, lines, _ in fake.scored:
        parts += [prompt, *[(x.ref, x.author, x.labels) for x in lines]]
    for prompt, lines in fake.verdicts:
        parts += [prompt, *[(x.ref, x.author, x.labels) for x in lines]]
    return json.dumps(parts, ensure_ascii=False)


def test_poll_verdict_reaches_the_wall_and_opted_out_guests_never_leave(live):
    core = live.core
    fake = FakeProvider(objects=[ports.DetectedObject("bow tie", "Fliege", 0.8, None)])
    svc = setup_llm(core, fake, detect={"local": True, "external": True})
    admin = live_admin(live)
    admin.put("/api/x/wall/admin/password", json={"password": "geheim-123"}, headers=live.origin)
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    admin.put("/api/x/wall/admin/config", json=config | {"delay_s": 0}, headers=live.origin)

    # four guests: one who allows everything, and one per way of staying out
    ok = add_guest(core, name="Flinker Fuchs", display_name="Partyfuchs")
    ai_out = add_guest(core, name="Stiller Otter", display_name="Geheimotter", ai_opt_out=True)
    ana_out = add_guest(core, name="Leiser Luchs", display_name="Nichtzeigen")
    banned = add_guest(core, name="Böser Bär", display_name="Bannbär")
    cool_pid, cool_photo = add_photo(core, ok, labels=("person", "sunglasses"))
    add_photo(core, ai_out, labels=("person", "hat"))
    add_photo(core, ana_out, labels=("dog",))
    _, hidden_photo = add_photo(core, ok, labels=("cake",), hidden=True)
    add_photo(core, banned, labels=("knife",))
    set_flags(core, ana_out, analysis=True)
    with core.db.tx() as c:
        c.execute("UPDATE users SET banned_at='2026-10-15T20:00:00Z' WHERE id=?", (banned,))

    def scores(lines):
        return {x.ref: [0.9 if lb == "sunglasses" else 0.1 for lb in x.labels] for x in lines}

    fake.score_fn = scores

    # the admin's property and the verdict category, through the API
    r = admin.post(
        f"{LLM}/properties",
        json={"name": "coolness", "prompt": "Wie cool ist jedes Objekt?"},
        headers=live.origin,
    )
    assert r.status_code == 201, r.text
    r = admin.post(
        CATEGORIES, json={"id": "coolstes", "spec": COOLEST_SPEC, "enabled": True},
        headers=live.origin,
    )  # fmt: skip
    assert r.status_code == 201, r.text

    # detection at upload ran for the allowed photo only
    wait_until(
        lambda: core.db.one(
            "SELECT 1 FROM photo_detection_runs WHERE photo_id=? AND source='claude'", (cool_pid,)
        ),
        timeout=10,
    )
    detected = {
        r["photo_id"]
        for r in core.db.all("SELECT photo_id FROM photo_detection_runs WHERE source='claude'")
    }
    assert detected == {cool_pid}
    assert len(fake.detected) == 1

    wall = live_wall(live, "geheim-123")
    stream = Stream(wall, "/livewall/api/stream")
    try:
        stream.until("hello")
        last = core.db.one("SELECT COALESCE(MAX(id), 0) AS n FROM llm_polls")["n"]
        r = admin.post(f"{LLM}/poll", headers=live.origin)
        assert r.json() == {"started": True, "reason": None}
        wait_until(lambda: _poll_done(core, last), timeout=10)
        # the hub announces the finished poll
        stream.until("categories.changed", timeout=5)
    finally:
        stream.close()

    stored = core.db.one("SELECT scores FROM property_scores WHERE photo_id=?", (cool_pid,))
    assert json.loads(stored["scores"]) == [0.1, 0.9, 0.1]  # + Claude's bow tie
    verdict = core.db.one("SELECT text, photo_id, object_idx FROM wall_category_verdicts")
    assert verdict["photo_id"] == cool_pid and "Partyfuchs" in verdict["text"]

    # the admin's category list and the wall screen show the verdict
    item = next(c for c in admin.get(CATEGORIES).json()["categories"] if c["id"] == "coolstes")
    assert item["verdict"]["text"] == verdict["text"]
    assert [w["photo_id"] for w in item["winners"]] == [cool_photo]
    screen = wall.get("/livewall/api/categories").json()["categories"]
    shown = next(c for c in screen if c["id"] == "coolstes")
    assert shown["verdict"] == {"text": verdict["text"], "emoji": "🏆", "photo_id": cool_photo}
    assert shown["winners"][0]["label"] == "Sunglasses"  # style object: the best object

    # nothing of the others ever left the server
    sent = _outbound(fake)
    assert "Partyfuchs" in sent and "sunglasses" in sent and "bow tie" in sent
    for leak in ("Geheimotter", "Stiller Otter", "Nichtzeigen", "Leiser Luchs", "Bannbär",
                 "Böser Bär", "hat", "dog", "knife", "cake", hidden_photo):  # fmt: skip
        assert leak not in sent, leak

    # opting out later takes the verdict naming the guest off the wall at once ...
    set_flags(core, ok, ai=True)
    screen = wall.get("/livewall/api/categories").json()["categories"]
    assert next(c for c in screen if c["id"] == "coolstes")["verdict"] is None
    # ... and leaves the guest out of the next poll
    last = core.db.one("SELECT COALESCE(MAX(id), 0) AS n FROM llm_polls")["n"]
    calls = len(fake.scored) + len(fake.verdicts)
    admin.post(f"{LLM}/poll", headers=live.origin)
    wait_until(lambda: core.db.one("SELECT 1 FROM llm_polls WHERE id > ? AND state != "
                                   "'running'", (last,)), timeout=10)  # fmt: skip
    assert len(fake.scored) + len(fake.verdicts) == calls  # nobody left to send
    screen = wall.get("/livewall/api/categories").json()["categories"]
    assert all(c["verdict"] is None for c in screen if c["id"] == "coolstes")
    del svc
    wall.close()
    admin.close()
