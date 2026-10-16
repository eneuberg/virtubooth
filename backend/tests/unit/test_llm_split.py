"""The external AI's two parts, each with its own switch under the master switch:
„Objekterkennung mit KI“ (detection at upload) and „Eigenschaften abfragen“ (the
poll with its verdicts). Off = that part sends nothing. The poll, the categories
and the values work on the merged object list."""

from __future__ import annotations

import json

import pytest

from virtubooth.extensions.wall.enrich import engine, values
from virtubooth.extensions.wall.llm import admin_api, config, flags, ports
from virtubooth.extensions.wall.llm.detect import DetectionRunner
from virtubooth.extensions.wall.llm.poller import eligible_photos, poll_once

from ..conftest import ORIGIN
from ..llm_fakes import (
    COOLEST_SPEC,
    FakeProvider,
    add_category,
    add_guest,
    add_photo,
    add_property,
    setup_llm,
    store_key,
)

BASE = "/api/x/wall/admin/llm"
DETECT = {"external": True}
# the AI sees the local person again (linked) and a hat (appended)
AI_OBJECTS = [
    ports.DetectedObject("man", "Mann", 0.9, (0.1, 0.1, 0.3, 0.8)),
    ports.DetectedObject("party hat", "Partyhut", 0.8, (0.15, 0.0, 0.1, 0.1)),
]


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def local_photo(core) -> tuple[int, str]:
    """A photo whose local detector found a person (framed) and a wine glass, and
    that the pipeline queued for the AI too: a legacy row from before the
    either/or (both lists, merged)."""
    pid, pub = add_photo(core, add_guest(core), labels=(), ai_detect=True)
    ports.append(core.db, pid, "local", "efficientdet_lite2@2", [
        ports.DetectedObject("person", "Person", 0.9, (0.1, 0.1, 0.3, 0.8)),
        ports.DetectedObject("wine glass", "Weinglas", 0.7, (0.5, 0.5, 0.1, 0.2)),
    ])  # fmt: skip
    return pid, pub


# ------------------------------------------------------------------- config


def test_a_stored_config_from_before_the_split_maps_onto_the_two_switches(core):
    """Before: no poll switch (the poll ran whenever external AI was on) and
    `detect.external` for the detection. Now: the poll reads as on, the detection
    switch stays what it was."""
    old = config.LlmConfig(enabled=True, detect=config.DetectConfig(external=True)).model_dump()
    del old["poll"]
    core.repos.app_settings.put(config.CONFIG_KEY, old, at="x")
    cfg = config.load_config(core.repos.app_settings)
    assert cfg.enabled and cfg.poll and cfg.detect.external
    old["detect"]["external"] = False
    core.repos.app_settings.put(config.CONFIG_KEY, old, at="x")
    cfg = config.load_config(core.repos.app_settings)
    assert cfg.poll and not cfg.detect.external
    # PUT one switch, the other stays
    new = config.merged(cfg, config.LlmConfigIn(poll=False))
    assert new.poll is False and new.detect.external is False and new.enabled


def test_put_switches_the_parts_independently(admin, core):
    store_key(core)
    r = admin.put(f"{BASE}/config", json={"enabled": True, "poll": False,
                                         "detect": DETECT}, headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["poll"] is False and cfg["detect"]["external"] is True
    cfg = admin.put(f"{BASE}/config", json={"poll": True}, headers=ORIGIN).json()["config"]
    assert cfg["poll"] is True and cfg["detect"]["external"] is True


# ------------------------------------------------------------ independence


def test_detection_off_poll_on(core):
    fake = FakeProvider(objects=AI_OBJECTS)
    svc = setup_llm(core, fake, poll=True)  # detect.external off (default)
    add_property(core)
    pid, _ = local_photo(core)
    assert DetectionRunner(svc).run_once() == "idle"
    assert fake.detected == []
    result = poll_once(svc)
    assert result is not None and result.state == "done"
    assert len(fake.scored) == 1
    assert svc.detector.state() == "off" and svc.poller.state() == "idle"
    assert [o.sources for o in ports.objects_of(core.db, [pid])[pid]] == [("local",), ("local",)]


def test_poll_off_detection_on(core):
    fake = FakeProvider(objects=AI_OBJECTS)
    svc = setup_llm(core, fake, poll=False, detect=DETECT)
    add_property(core)
    add_category(core, "coolstes_objekt", COOLEST_SPEC)
    local_photo(core)
    assert poll_once(svc) is None  # nothing sent, no llm_polls row
    assert fake.scored == [] and fake.verdicts == []
    assert core.db.one("SELECT COUNT(*) FROM llm_polls")[0] == 0
    assert svc.poller.trigger() == (False, "„Eigenschaften abfragen“ ist ausgeschaltet.")
    assert DetectionRunner(svc).run_once() == "done"
    assert len(fake.detected) == 1
    assert svc.poller.state() == "off" and svc.detector.state() == "idle"
    kinds = {r["kind"] for r in core.db.all("SELECT kind FROM llm_usage")}
    assert kinds == {"detect"}


def test_master_off_sends_nothing_whatever_the_parts_say(core):
    fake = FakeProvider(objects=AI_OBJECTS)
    svc = setup_llm(core, fake, enabled=False, poll=True, detect=DETECT)
    add_property(core)
    local_photo(core)
    assert DetectionRunner(svc).run_once() == "idle"
    assert poll_once(svc) is None
    assert fake.detected == [] and fake.scored == []
    assert svc.poller.state() == "off" and svc.detector.state() == "off"
    assert core.db.one("SELECT COUNT(*) FROM llm_usage")[0] == 0
    assert flags.external_ai_active(core.repos) is False


def test_external_ai_active_follows_the_parts(core):
    setup_llm(core, None, poll=False)
    add_property(core)
    assert flags.external_ai_active(core.repos) is False  # the poll is off, detection too
    setup_llm(core, None, poll=True)
    assert flags.external_ai_active(core.repos) is True
    setup_llm(core, None, poll=False, detect=DETECT)
    assert flags.external_ai_active(core.repos) is True


def test_status_shows_each_part_on_its_own(admin, core):
    fake = FakeProvider(objects=AI_OBJECTS)
    svc = setup_llm(core, fake, poll=False, detect=DETECT)
    local_photo(core)
    body = admin.get(BASE).json()
    assert body["poller"]["state"] == "off"
    assert body["detection"]["state"] in {"idle", "running"}
    svc.detector.run_once()  # (the app's own runner may have been quicker)
    body = admin.get(BASE).json()
    assert body["detection"]["done"] == 1 and body["detection"]["last_run_at"] is not None
    assert body["detection"]["last_error"] is None and body["poller"]["last_error"] is None


# --------------------------------------------------------------- merged list


def test_the_poll_and_the_categories_work_on_the_merged_list(core):
    fake = FakeProvider(objects=AI_OBJECTS)
    svc = setup_llm(core, fake, detect=DETECT)
    prop = add_property(core)
    pid, _ = local_photo(core)
    assert DetectionRunner(svc).run_once() == "done"
    merged = ports.objects_of(core.db, [pid])[pid]
    assert [(o.idx, o.label, o.sources) for o in merged] == [
        (0, "person", ("local", "claude")),
        (1, "wine glass", ("local",)),
        (2, "party hat", ("claude",)),
    ]
    (photo,) = eligible_photos(core.db)
    assert photo.labels == ("person", "wine glass", "party hat")  # the person once
    assert poll_once(svc) is not None
    (_, lines, _) = fake.scored[0]
    assert lines[0].labels == ("person", "wine glass", "party hat")
    stored = core.db.one("SELECT scores FROM property_scores WHERE property_id=?", (prop,))
    assert stored is not None and len(json.loads(stored[0])) == 3
    # the categories' snapshot and the value catalogue read the merged list too
    snap = engine.snapshot(core.db).photos[pid]
    assert [o[1] for o in snap.objects] == ["person", "wine glass", "party hat"]
    labels = {i.label: i.count for i in values.labels_seen(core.db)}
    assert labels == {"person": 1, "wine glass": 1, "party hat": 1}
    assert values.has_external_objects(core.db) is True
