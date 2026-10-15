"""External object detection at upload (PLAN-NIGHT N9): after the local list,
once per photo, never for an opted-out guest."""

from __future__ import annotations

import io

from PIL import Image

from virtubooth.extensions.wall.llm import ports
from virtubooth.extensions.wall.llm.detect import DetectionRunner, downscale
from virtubooth.extensions.wall.llm.providers.base import ProviderError, TokenUsage

from ..llm_fakes import FakeProvider, add_guest, add_photo, jpeg_bytes, set_flags, setup_llm

EXTERNAL = {"local": True, "external": True}


def runs(core, pid):
    """The photo's external detection runs."""
    return core.db.all(
        "SELECT source, state, model, error, objects FROM photo_detection_runs "
        "WHERE photo_id=? AND source != 'local' ORDER BY source",
        (pid,),
    )


def test_appends_after_the_local_objects(core):
    fake = FakeProvider(
        objects=[
            ports.DetectedObject("hat", "Hut", 0.9, (0.1, 0.1, 0.2, 0.2)),
            ports.DetectedObject("disco ball", "Discokugel", 0.7, None),
        ]
    )
    svc = setup_llm(core, fake, detect=EXTERNAL)
    pid, public_id = add_photo(core, add_guest(core), labels=("person", "wine glass"))
    rev_before = core.db.one("SELECT rev FROM wall_analysis WHERE photo_id=?", (pid,))["rev"]
    runner = DetectionRunner(svc)
    assert runner.run_once() == "done"
    objs = ports.objects_of(core.db, [pid])[pid]
    assert [(o.idx, o.label, o.source) for o in objs] == [
        (0, "person", "local"),
        (1, "wine glass", "local"),
        (2, "hat", "claude"),
        (3, "disco ball", "claude"),
    ]
    assert objs[2].box == (0.1, 0.1, 0.2, 0.2) and objs[3].box is None
    assert objs[2].model == "claude-haiku-5-5"
    assert [dict(r) for r in runs(core, pid)] == [{
        "source": "claude", "state": "done", "model": "claude-haiku-5-5", "error": None,
        "objects": 2,
    }]  # fmt: skip
    # walls refetch the photo
    assert core.db.one("SELECT rev FROM wall_analysis WHERE photo_id=?", (pid,))["rev"] > rev_before
    usage = core.db.one("SELECT kind, ref, ok FROM llm_usage")
    assert dict(usage) == {"kind": "detect", "ref": public_id, "ok": 1}


def test_once_per_photo_newest_first(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake, detect=EXTERNAL)
    uid = add_guest(core)
    old, _ = add_photo(core, uid, age_s=600)
    new, _ = add_photo(core, uid, age_s=60)
    runner = DetectionRunner(svc)
    assert runner.run_once() == "done"
    assert [r["source"] for r in runs(core, new)] == ["claude"] and runs(core, old) == []
    assert runner.run_once() == "done"
    assert runner.run_once() == "idle"
    assert len(fake.detected) == 2
    # frozen: the source cannot run again for the photo
    try:
        ports.append(core.db, new, "claude", "x", [])
    except ports.FrozenError:
        pass
    else:
        raise AssertionError("second run was accepted")


def test_waits_for_the_local_pipeline(core):
    svc = setup_llm(core, FakeProvider(), detect=EXTERNAL)
    pid, _ = add_photo(core, add_guest(core), state="pending", labels=())
    assert DetectionRunner(svc).run_once() == "idle"
    with core.db.tx() as c:
        c.execute("UPDATE wall_analysis SET state='failed' WHERE photo_id=?", (pid,))
    assert DetectionRunner(svc).run_once() == "done"


def test_opted_out_guests_are_never_sent(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake, detect=EXTERNAL)
    no_ai = add_guest(core, ai_opt_out=True)
    no_analysis = add_guest(core, analysis_opt_out=True)
    add_photo(core, no_ai)
    add_photo(core, no_analysis)
    add_photo(core, add_guest(core), hidden=True)
    runner = DetectionRunner(svc)
    assert runner.run_once() == "idle"
    assert fake.detected == []
    assert (
        core.db.one("SELECT COUNT(*) AS n FROM photo_detection_runs WHERE source='claude'")["n"]
        == 0
    )


def test_flags_are_read_again_right_before_sending(core, monkeypatch):
    fake = FakeProvider()
    svc = setup_llm(core, fake, detect=EXTERNAL)
    uid = add_guest(core)
    pid, _ = add_photo(core, uid)
    real = ports.eligible_for_external

    def stale(db, source, limit):
        found = real(db, source, limit)
        set_flags(core, uid, ai=True)  # the guest opts out between query and send
        return found

    monkeypatch.setattr(ports, "eligible_for_external", stale)
    assert DetectionRunner(svc).run_once() == "idle"
    assert fake.detected == [] and runs(core, pid) == []


def test_failure_is_recorded_and_not_retried(core):
    fake = FakeProvider(
        fail=ProviderError(
            "Antwort war kein gültiges JSON.", kind="bad_output", usage=TokenUsage(900, 40)
        )
    )
    svc = setup_llm(core, fake, detect=EXTERNAL)
    pid, _ = add_photo(core, add_guest(core))
    runner = DetectionRunner(svc)
    assert runner.run_once() == "done"
    run = runs(core, pid)[0]
    assert run["state"] == "failed" and run["error"] == "Antwort war kein gültiges JSON."
    assert runner.run_once() == "idle"
    assert len(fake.detected) == 1
    assert dict(core.db.one("SELECT ok, input_tokens FROM llm_usage")) == {
        "ok": 0,
        "input_tokens": 900,
    }


def test_provider_trouble_is_not_the_photos_fault(core):
    fake = FakeProvider(fail=ProviderError("Der API-Schlüssel wurde abgelehnt.", kind="auth"))
    svc = setup_llm(core, fake, detect=EXTERNAL)
    pid, _ = add_photo(core, add_guest(core))
    runner = DetectionRunner(svc)
    assert runner.run_once() == "backoff"
    assert runs(core, pid) == [] and runner.last_error == "Der API-Schlüssel wurde abgelehnt."
    fake.fail = None
    assert runner.run_once() == "done"


def test_off_unless_enabled_and_external(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)  # detect.external stays off
    add_photo(core, add_guest(core))
    assert DetectionRunner(svc).run_once() == "idle"
    setup_llm(core, fake, enabled=False, detect=EXTERNAL)
    assert DetectionRunner(svc).run_once() == "idle"
    assert fake.detected == []


def test_sent_image_is_small_and_without_metadata(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake, detect=EXTERNAL)
    add_photo(core, add_guest(core), image=jpeg_bytes(2400, 1800, exif=True))
    DetectionRunner(svc).run_once()
    sent = fake.detected[0]
    img = Image.open(io.BytesIO(sent))
    assert img.format == "JPEG" and max(img.size) == 1024
    assert not img.getexif() and b"SecretCam" not in sent


def test_downscale_keeps_small_images():
    img = Image.open(io.BytesIO(downscale(jpeg_bytes(640, 480), 1024)))
    assert img.size == (640, 480)
