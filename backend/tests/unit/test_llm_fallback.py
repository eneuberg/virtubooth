"""The local detector as fallback for the AI detection: when the AI cannot
detect any more (no key, key unreadable or rejected, budget used up, the
provider down for minutes, a model it does not know) the stored choice becomes
„Lokal“ by itself (persisted, audit-logged, with a notice) and photos still
queued for the AI get the local detector's list in a second worker pass; so
does a photo the AI fails on. Facts stay frozen, the merged list holds that one
source; once „KI“ is chosen again new photos go to it, fallen-back ones stay."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from virtubooth.core.clock import iso
from virtubooth.db.migrations import SCHEMA_V16, statements
from virtubooth.extensions.wall.enrich import admin_api as enrich_api
from virtubooth.extensions.wall.enrich import jobs, objects
from virtubooth.extensions.wall.enrich.analyzers.basic import BasicAnalyzer
from virtubooth.extensions.wall.enrich.worker import Worker
from virtubooth.extensions.wall.llm import admin_api, config, crypto, ports
from virtubooth.extensions.wall.llm import detect as detect_mod
from virtubooth.extensions.wall.llm.detect import DetectionRunner
from virtubooth.extensions.wall.llm.providers.base import ProviderError
from virtubooth.extensions.wall.llm.service import Unavailable

from ..conftest import ORIGIN
from ..llm_fakes import API_KEY, FakeProvider, add_guest, add_photo, set_flags, setup_llm
from .test_llm_either_or import AI, FakeDetector

UNREADABLE = "Der API-Schlüssel für Anthropic (Claude, USA) ist nicht lesbar"
LIMITS = {"party_usd": None, "party_calls": None, "daily_usd": None, "daily_calls": None}


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")
    app.include_router(enrich_api.router, prefix="/api/x/wall")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def worker(core) -> Worker:
    return Worker(core.settings.data_dir, analyzers=[BasicAnalyzer(), FakeDetector()],
                  watch_parent=False)  # fmt: skip


def ai_mode(core, fake: FakeProvider | None = None, **changes):
    """The AI is the detector (local switched off), the fake its provider."""
    svc = setup_llm(core, fake or FakeProvider(objects=AI), detect={"external": True},
                    budget=dict(LIMITS), **changes)  # fmt: skip
    ports.set_local_objects(core, False, by="t")
    runner = DetectionRunner(svc)
    runner.clock = Clock()
    svc.detector = runner
    return svc, runner


def mode(core) -> str:
    cfg = config.load_config(core.repos.app_settings)
    if cfg.detect.external:
        return "ai"
    return "off" if "objects" in jobs.disabled_analyzers(core.repos.app_settings) else "local"


def notice(core) -> str | None:
    return config.load_notice(core.repos.app_settings)[0]


def assert_switched_to_local(core, reason: str) -> None:
    """The stored choice is „Lokal“ now, with the reason as notice and in the audit."""
    assert mode(core) == "local"
    assert notice(core) is not None and notice(core).startswith(reason)
    entry = next(e for e in core.repos.audit.list(20) if e.action == "llm.detection")
    assert entry.actor == "system" and entry.details["auto"] is True
    assert entry.details["mode"] == "local" and entry.details["reason"] == notice(core)


def queued(core, uid=None) -> int:
    """A new photo the worker finished while the AI is the detector: queued for it."""
    pid, _ = add_photo(core, uid or add_guest(core), state="pending", labels=())
    claimed = jobs.claim(core.db)
    assert claimed is not None and claimed.id == pid
    assert worker(core).process(core.repos, claimed) == "done"
    row = core.db.one("SELECT ai_detect FROM wall_analysis WHERE photo_id=?", (pid,))
    assert row["ai_detect"] == 1 and not objects.has_run(core.db, pid, "local")
    return pid


def local_pass(core) -> list[int]:
    """The worker's second pass over every photo the AI handed back."""
    done = []
    w = worker(core)
    while (photo := jobs.claim_fallback(core.db)) is not None:
        w.process_fallback(core.repos, photo)
        done.append(photo.id)
    return done


def frozen(core, pid):
    """What must not change when the local detector stands in."""
    row = jobs.get(core.db, pid)
    assert row is not None
    data = {k: v for k, v in row.data.items() if k != jobs.AI_FALLBACK}
    return jobs.facts(core.db, pid), data, row.versions, row.state, row.finished_at


def run_of(core, pid, source="claude"):
    r = core.db.one(
        "SELECT state, error, objects FROM photo_detection_runs WHERE photo_id=? AND source=?",
        (pid, source),
    )
    return dict(r) if r is not None else None


def assert_local_only(core, pid, reason):
    merged = ports.objects_of(core.db, [pid])[pid]
    assert [(o.idx, o.label, o.sources) for o in merged] == [(0, "person", ("local",))]
    assert set(objects.source_objects_of(core.db, pid)) == {"local"}
    assert jobs.get(core.db, pid).data[jobs.AI_FALLBACK] == reason
    assert run_of(core, pid, "local") == {"state": "done", "error": None, "objects": 1}


# ------------------------------------------------- the AI cannot take any


def _no_key(core, svc):
    svc.keys.clear("anthropic")


def _unreadable_key(core, svc):
    other = crypto.KeyStore(core.repos.app_settings, "another-secret-key-0123456789abcdef")
    other.put("anthropic", API_KEY, by="t", at=iso(datetime.now(UTC)))


def _budget(core, svc):
    setup_llm(core, None, detect={"external": True}, budget={**LIMITS, "party_calls": 0})


@pytest.mark.parametrize(
    ("cause", "reason", "error"),
    [
        (_no_key, jobs.NO_KEY, "Kein API-Schlüssel für Anthropic (Claude, USA) gesetzt."),
        (_unreadable_key, jobs.KEY_INVALID, UNREADABLE),
        (_budget, jobs.BUDGET, "Budget erreicht"),
    ],
)
def test_queued_photos_fall_back_at_once_while_the_ai_cannot_take_any(core, cause, reason, error):
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    uid = add_guest(core)
    first, second = queued(core, uid), queued(core, uid)
    before = {pid: frozen(core, pid) for pid in (first, second)}
    cause(core, svc)
    assert runner.fallback_now() == reason
    assert runner.run_once() == "done"
    assert fake.detected == []  # nothing went out
    assert_switched_to_local(core, error)
    assert objects.count_eligible_for_external(core.db, "claude") == 0
    for pid in (first, second):
        run = run_of(core, pid)
        assert run["state"] == "skipped" and run["error"].startswith(error)
    assert local_pass(core) == [second, first]
    for pid in (first, second):
        assert_local_only(core, pid, reason)
        assert frozen(core, pid) == before[pid]  # facts, data, versions untouched
    # nothing left for either side
    assert runner.run_once() == "idle" and local_pass(core) == []


def test_a_rejected_key_switches_to_local_and_hands_the_queue_back(core):
    fake = FakeProvider(objects=AI, fail=ProviderError("Der API-Schlüssel wurde abgelehnt.",
                                                       kind="auth"))  # fmt: skip
    svc, runner = ai_mode(core, fake)
    uid = add_guest(core)
    first, second = queued(core, uid), queued(core, uid)
    assert runner.run_once() == "done" and len(fake.detected) == 1
    # the newest was tried and failed, the other one is handed back without asking
    assert run_of(core, second) == {"state": "failed", "objects": 0,
                                    "error": "Der API-Schlüssel wurde abgelehnt."}  # fmt: skip
    assert run_of(core, first)["state"] == "skipped"
    assert_switched_to_local(core, "Der API-Schlüssel wurde abgelehnt.")
    local_pass(core)
    for pid in (first, second):
        assert_local_only(core, pid, jobs.KEY_INVALID)
    # „KI“ again with the same key: refused, it stays „Lokal“
    assert "abgelehnt" in (svc.ai_unavailable() or "")
    with pytest.raises(Unavailable) as exc:
        svc.set_detection("ai", actor="admin:t")
    assert exc.value.code == "ai_detection_unavailable" and mode(core) == "local"
    assert notice(core) is None  # the host chose: the old notice is gone
    # a new key: „KI“ can be chosen again, new photos go to the AI, the old ones stay local
    fake.fail = None
    svc.set_key("anthropic", API_KEY + "-new", actor="t")
    assert svc.ai_unavailable() is None
    svc.set_detection("ai", actor="admin:t")
    third = queued(core, uid)
    assert runner.run_once() == "done" and len(fake.detected) == 2
    assert [o.source for o in ports.objects_of(core.db, [third])[third]] == ["claude"]
    assert runner.run_once() == "idle" and len(fake.detected) == 2
    for pid in (first, second):
        assert_local_only(core, pid, jobs.KEY_INVALID)


def test_a_rejected_key_is_tried_again_after_a_while_or_a_passing_test(core):
    fake = FakeProvider(objects=AI, fail=ProviderError("abgelehnt", kind="auth"))
    svc, runner = ai_mode(core, fake)
    queued(core)
    runner.run_once()
    assert mode(core) == "local" and "abgelehnt" in (svc.ai_unavailable() or "")
    runner.clock.now += detect_mod.AUTH_RETRY_S
    assert svc.ai_unavailable() is None  # the same key gets another try
    runner._rejected = (runner._fingerprint(API_KEY), runner.clock.now)
    assert svc.ai_unavailable() is not None
    fake.fail = None
    assert svc.test_key()[0] and svc.ai_unavailable() is None


def test_an_unknown_model_switches_to_local(core):
    fake = FakeProvider(objects=AI, fail=ProviderError("Modell beim Anbieter nicht gefunden.",
                                                       kind="model"))  # fmt: skip
    _, runner = ai_mode(core, fake)
    pid = queued(core)
    assert runner.run_once() == "done"
    assert_switched_to_local(core, "Modell beim Anbieter nicht gefunden.")
    local_pass(core)
    assert_local_only(core, pid, jobs.MODEL_UNKNOWN)


def test_a_photo_queued_while_the_choice_changed_goes_local(core):
    """The worker was mid-photo when the host chose „Lokal“: the photo it queued for
    the AI afterwards gets the local list, it is not stranded."""
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    pid = queued(core)
    svc.set_detection("local", actor="admin:t")
    assert runner.run_once() == "done" and fake.detected == []
    local_pass(core)
    assert_local_only(core, pid, jobs.AI_OFF)
    # „Aus“: nothing stands in (no local detector chosen)
    svc.set_detection("ai", actor="admin:t")
    other = queued(core)
    svc.set_detection("off", actor="admin:t")
    assert runner.run_once() == "idle" and run_of(core, other) is None


# ------------------------------------------------------- provider trouble


def test_provider_trouble_switches_to_local_after_a_few_minutes(core):
    fake = FakeProvider(objects=AI, fail=ProviderError("KI-Dienst nicht erreichbar.",
                                                       kind="network"))  # fmt: skip
    svc, runner = ai_mode(core, fake)
    uid = add_guest(core)
    pid = queued(core, uid)
    assert runner.run_once() == "backoff"
    runner.clock.now += detect_mod.FALLBACK_AFTER_S - 1
    assert runner.run_once() == "backoff"
    assert run_of(core, pid) is None and runner.fallback_now() is None
    assert mode(core) == "ai"  # a short outage changes nothing
    newer = queued(core, uid)
    runner.clock.now += 1
    assert runner.fallback_now() == jobs.UNREACHABLE
    # the trouble is old now: „Lokal“, every queued photo goes local
    assert runner.run_once() == "done"
    assert_switched_to_local(core, "Der KI-Dienst antwortet seit 5 Minuten nicht "
                                   "(KI-Dienst nicht erreichbar).")  # fmt: skip
    for p in (pid, newer):
        assert run_of(core, p)["state"] == "skipped"
    assert local_pass(core) == [newer, pid]
    for p in (pid, newer):
        assert_local_only(core, p, jobs.UNREACHABLE)
    # the provider is back and „KI“ chosen again: the next photo goes to the AI
    fake.fail = None
    svc.set_detection("ai", actor="admin:t")
    newest = queued(core, uid)
    assert runner.run_once() == "done"
    assert [o.source for o in ports.objects_of(core.db, [newest])[newest]] == ["claude"]
    assert runner.fallback_now() is None and runner.trouble_since is None
    assert runner.run_once() == "idle"  # the fallen-back photos are never sent


@pytest.mark.parametrize("kind", ["rate", "server"])
def test_rate_limits_and_server_errors_count_as_provider_trouble(core, kind):
    fake = FakeProvider(objects=AI, fail=ProviderError("gestört", kind=kind))
    _, runner = ai_mode(core, fake)
    pid = queued(core)
    assert runner.run_once() == "backoff"
    runner.clock.now += detect_mod.FALLBACK_AFTER_S
    assert runner.run_once() == "done"
    local_pass(core)
    assert_local_only(core, pid, jobs.UNREACHABLE)


@pytest.mark.parametrize("kind", ["bad_output", "refused", "other"])
def test_an_error_about_one_photo_hands_that_photo_back(core, kind):
    fake = FakeProvider(objects=AI, fail=ProviderError("Antwort ohne Text.", kind=kind))
    _, runner = ai_mode(core, fake)
    uid = add_guest(core)
    other = queued(core, uid)
    bad = queued(core, uid)
    assert runner.run_once() == "done"
    assert run_of(core, bad) == {"state": "failed", "error": "Antwort ohne Text.", "objects": 0}
    assert runner.fallback_now() is None  # just that photo
    fake.fail = None
    assert runner.run_once() == "done"
    assert local_pass(core) == [bad]
    assert_local_only(core, bad, jobs.PHOTO_FAILED)
    assert [o.source for o in ports.objects_of(core.db, [other])[other]] == ["claude"]


def test_an_unreadable_photo_falls_back(core):
    fake = FakeProvider(objects=AI)
    _, runner = ai_mode(core, fake)
    pid = queued(core)
    row = core.db.one("SELECT extension, filename FROM photos WHERE id=?", (pid,))
    core.repos.photos.path(row["extension"], row["filename"]).write_bytes(b"not a jpeg")
    assert runner.run_once() == "done" and fake.detected == []
    assert run_of(core, pid)["error"] == "Foto nicht lesbar."
    assert jobs.get(core.db, pid).data[jobs.AI_FALLBACK] == jobs.PHOTO_FAILED
    local_pass(core)  # the local detector cannot read it either: recorded, final
    assert run_of(core, pid, "local")["state"] == "failed"
    assert jobs.claim_fallback(core.db) is None


# --------------------------------------------------------------- recovery


def test_budget_used_up_switches_to_local_until_chosen_again(core):
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    uid = add_guest(core)
    old = queued(core, uid)
    _budget(core, svc)
    runner.run_once()
    assert_switched_to_local(core, "Budget erreicht")
    local_pass(core)
    assert_local_only(core, old, jobs.BUDGET)
    # „Lokal“ now: new photos get the local list as such (no fallback mark)
    direct = analyse_new(core, uid)
    assert jobs.AI_FALLBACK not in jobs.get(core.db, direct).data
    assert [o.source for o in ports.objects_of(core.db, [direct])[direct]] == ["local"]
    # „KI“ is refused while the budget lasts
    with pytest.raises(Unavailable):
        svc.set_detection("ai", actor="admin:t")
    # budget raised, „KI“ chosen again: new photos go to the AI
    setup_llm(core, None, budget=dict(LIMITS))
    svc.set_detection("ai", actor="admin:t")
    new = queued(core, uid)
    assert runner.run_once() == "done" and len(fake.detected) == 1
    assert runner.run_once() == "idle" and len(fake.detected) == 1
    assert [o.source for o in ports.objects_of(core.db, [new])[new]] == ["claude"]
    assert run_of(core, new, "local") == {"state": "skipped", "error": jobs.AI_ACTIVE,
                                          "objects": 0}  # fmt: skip
    assert_local_only(core, old, jobs.BUDGET)


def analyse_new(core, uid) -> int:
    pid, _ = add_photo(core, uid, state="pending", labels=())
    claimed = jobs.claim(core.db)
    assert claimed is not None
    worker(core).process(core.repos, claimed)
    return pid


# ------------------------------------------------------------- edge cases


def test_the_worker_loop_runs_the_local_pass(core):
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    pid = queued(core)
    svc.keys.clear("anthropic")
    runner.run_once()
    assert jobs.fallback_due(core.db)
    assert worker(core).run(once=True) == 0
    assert not jobs.fallback_due(core.db)
    assert_local_only(core, pid, jobs.NO_KEY)


def test_a_guest_who_opted_out_meanwhile_gets_no_local_list(core):
    _, runner = ai_mode(core, FakeProvider(objects=AI, fail=ProviderError("x", kind="other")))
    uid = add_guest(core)
    pid = queued(core, uid)
    runner.run_once()
    set_flags(core, uid, analysis=True)
    local_pass(core)
    assert ports.objects_of(core.db, [pid]) == {}
    assert run_of(core, pid, "local")["state"] == "skipped"


def test_a_photo_with_its_local_run_decided_stays_queued(core):
    """Photos with both lists (from before the either/or) cannot fall back: while
    the AI cannot take them they keep waiting, as before."""
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    pid, _ = add_photo(core, add_guest(core), ai_detect=True)  # with a local list
    svc.keys.clear("anthropic")
    assert runner.run_once() == "idle"
    assert run_of(core, pid) is None and "objects_fallback" not in jobs.get(core.db, pid).data
    assert objects.count_eligible_for_external(core.db, "claude") == 1


def test_the_handed_back_photo_is_never_handed_back_twice(core):
    _, runner = ai_mode(core, FakeProvider(objects=AI, fail=ProviderError("x", kind="other")))
    pid = queued(core)
    runner.run_once()
    local_pass(core)
    assert not jobs.hand_to_local(core.db, pid, jobs.BUDGET)
    assert not jobs.finish_fallback(core.db, pid, objects_model="m")
    assert_local_only(core, pid, jobs.PHOTO_FAILED)


def test_migration_reopens_the_local_run_of_photos_still_waiting_for_the_ai(core):
    uid = add_guest(core)
    waiting, _ = add_photo(core, uid, labels=(), ai_detect=True)
    delivered, _ = add_photo(core, uid, labels=(), ai_detect=True)
    local_only, _ = add_photo(core, uid, labels=(), ai_detect=False)
    for pid in (waiting, delivered, local_only):
        objects.record_run(core.db, pid, "local", "skipped", None, jobs.AI_ACTIVE)
    ports.append(core.db, delivered, "claude", "m", AI)
    with core.db.tx() as c:
        for sql in statements(SCHEMA_V16):
            c.execute(sql)
    assert not objects.has_run(core.db, waiting, "local")
    assert objects.has_run(core.db, delivered, "local")
    assert objects.has_run(core.db, local_only, "local")


# ------------------------------------------------------------------ admin


def test_the_status_and_the_photo_show_the_fallback(admin, core):
    fake = FakeProvider(objects=AI)
    svc, runner = ai_mode(core, fake)
    uid = add_guest(core)
    pid = queued(core, uid)
    body = admin.get("/api/x/wall/admin/llm").json()["detection"]
    assert (body["fallback"], body["fallback_reason"], body["fallback_now"]) == (0, None, None)
    assert (body["mode"], body["notice"], body["ai_unavailable"]) == ("ai", None, None)
    svc.keys.clear("anthropic")
    runner.run_once()
    local_pass(core)
    no_key = "Kein API-Schlüssel für Anthropic (Claude, USA) gesetzt."
    body = admin.get("/api/x/wall/admin/llm").json()["detection"]
    assert body["fallback"] == 1 and body["fallback_reason"] == jobs.NO_KEY
    # the choice is „Lokal“ now, with the reason; „KI“ would be refused for the same one
    assert body["mode"] == "local" and body["fallback_now"] is None
    assert body["notice"] == no_key and body["notice_at"] is not None
    assert body["ai_unavailable"] == no_key
    public_id = core.db.one("SELECT public_id FROM photos WHERE id=?", (pid,))[0]
    photo = admin.get(f"/api/x/wall/admin/photos/{public_id}/analysis").json()
    assert photo["objects_fallback"] == jobs.NO_KEY
    assert [o["source"] for o in photo["objects"]] == ["local"]
    # the key is back: „KI“ possible again, the notice stays until the host chooses
    svc.set_key("anthropic", API_KEY, actor="t")
    body = admin.get("/api/x/wall/admin/llm").json()["detection"]
    assert body["ai_unavailable"] is None and body["notice"] == no_key
    r = admin.put("/api/x/wall/admin/llm/object-detection", json={"mode": "ai"},
                  headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()["detection"]
    assert body["mode"] == "ai" and body["notice"] is None and body["fallback"] == 1
    # an AI photo has no fallback
    new = queued(core, uid)
    runner.run_once()
    public_id = core.db.one("SELECT public_id FROM photos WHERE id=?", (new,))[0]
    assert (
        admin.get(f"/api/x/wall/admin/photos/{public_id}/analysis").json()["objects_fallback"]
        is None
    )
