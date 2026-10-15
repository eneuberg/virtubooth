"""The poll (PLAN-NIGHT N8): property scores aligned with the object lists,
latest values only, skipped when nothing changed; then the category verdicts."""

from __future__ import annotations

import json

from virtubooth.extensions.wall.llm import poller
from virtubooth.extensions.wall.llm.poller import poll_once
from virtubooth.extensions.wall.llm.providers.base import ProviderError, VerdictOut

from ..llm_fakes import (
    COOLEST_SPEC,
    FakeProvider,
    add_category,
    add_guest,
    add_photo,
    add_property,
    set_flags,
    setup_llm,
)


def scores(core, prop_id):
    return {
        r["photo_id"]: json.loads(r["scores"])
        for r in core.db.all(
            "SELECT photo_id, scores FROM property_scores WHERE property_id=?", (prop_id,)
        )
    }


def polls(core):
    return [
        dict(r) for r in core.db.all("SELECT id, state, photos, error FROM llm_polls ORDER BY id")
    ]


def test_scores_are_stored_aligned(core):
    def answer(lines):
        return {x.ref: [round(0.1 * (i + 1), 1) for i in range(len(x.labels))] for x in lines}

    fake = FakeProvider(score_fn=answer)
    svc = setup_llm(core, fake)
    prop = add_property(core)
    a, a_pub = add_photo(core, add_guest(core, name="Flinker Fuchs"), labels=("person", "hat"))
    b, _ = add_photo(core, add_guest(core, instagram="anna.b"), labels=("dog",))
    result = poll_once(svc)
    assert result is not None and result.state == "done"
    assert scores(core, prop) == {a: [0.1, 0.2], b: [0.1]}
    prompt, lines, relative = fake.scored[0]
    assert prompt == "Wie cool ist das?" and relative is False
    assert [(x.ref, x.author, x.labels) for x in lines] == [
        (f"P{a_pub}", "Flinker Fuchs", ("person", "hat")),
        (lines[1].ref, "@anna.b", ("dog",)),
    ]
    assert polls(core) == [{"id": result.poll_id, "state": "done", "photos": 2, "error": None}]
    row = core.db.one("SELECT poll_id FROM property_scores LIMIT 1")
    assert row["poll_id"] == result.poll_id


def test_wrong_length_and_unknown_ids_are_dropped(core):
    def answer(lines):
        out = {x.ref: [0.9] * (len(x.labels) + 1) for x in lines}  # one too many
        out["Pnot-sent"] = [1.0]
        return out

    svc = setup_llm(core, FakeProvider(score_fn=answer))
    prop = add_property(core)
    add_photo(core, add_guest(core))
    poll_once(svc)
    assert scores(core, prop) == {}


def test_out_of_range_values_are_clamped_by_the_parser():
    from virtubooth.extensions.wall.llm.prompts import parse_scores
    from virtubooth.extensions.wall.llm.providers.base import TokenUsage

    parsed = parse_scores(
        {"photos": [{"id": "Pa", "scores": [1.7, -2, "x", None, 0.25]}, {"id": 3}]}, TokenUsage()
    )
    assert parsed == {"Pa": [1.0, 0.0, None, None, 0.25]}


def test_archived_properties_are_not_polled(core):
    from virtubooth.extensions.wall.llm import properties

    fake = FakeProvider()
    svc = setup_llm(core, fake)
    prop = add_property(core)
    add_property(core, "lustigkeit", "Wie lustig?")
    add_photo(core, add_guest(core))
    properties.set_archived(core.db, core.repos.audit, "lustigkeit", True, actor="t")
    poll_once(svc)
    assert [p for p, _, _ in fake.scored] == ["Wie cool ist das?"]
    assert len(scores(core, prop)) == 1


def test_latest_values_only_and_skip_when_unchanged(core):
    value = {"v": 0.2}
    fake = FakeProvider(score_fn=lambda lines: {x.ref: [value["v"]] * len(x.labels) for x in lines})
    svc = setup_llm(core, fake)
    prop = add_property(core)
    pid, _ = add_photo(core, add_guest(core), labels=("hat",))
    poll_once(svc)
    # nothing changed: skipped, no call
    second = poll_once(svc)
    assert second is not None and second.state == "skipped"
    assert len(fake.scored) == 1
    # a forced poll (POST /llm/poll) runs anyway and overwrites
    value["v"] = 0.8
    poll_once(svc, force=True)
    assert scores(core, prop) == {pid: [0.8]}
    assert core.db.one("SELECT COUNT(*) AS n FROM property_scores")["n"] == 1
    # a new photo changes the input
    add_photo(core, add_guest(core), labels=("dog",))
    assert poll_once(svc).state == "done"
    assert [p["state"] for p in polls(core)] == ["done", "skipped", "done", "done"]


def test_opted_out_guests_are_not_sent(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)
    add_property(core)
    ok_uid = add_guest(core, name="Darf")
    add_photo(core, ok_uid)
    add_photo(core, add_guest(core, name="KeineKI", ai_opt_out=True))
    add_photo(core, add_guest(core, name="KeineAuswertung", analysis_opt_out=True))
    add_photo(core, add_guest(core, name="Versteckt"), hidden=True)
    add_photo(core, add_guest(core, name="Wartet"), state="pending")
    poll_once(svc)
    sent = [x.author for _, lines, _ in fake.scored for x in lines]
    assert sent == ["Darf"]
    # opting out later: the next poll does not send it any more
    set_flags(core, ok_uid, ai=True)
    assert poll_once(svc, force=True) is not None
    assert len(fake.scored) == 1


def test_chunks_of_at_most_400_objects():
    photos = [poller.PolledPhoto(i, f"p{i}", 1, "x", ("a",) * 150) for i in range(5)]
    parts = poller.chunks(photos)
    assert [sum(len(p.labels) for p in part) for part in parts] == [300, 300, 150]


def test_large_lists_go_out_in_chunks(core, monkeypatch):
    monkeypatch.setattr(poller, "MAX_OBJECTS_PER_CALL", 3)
    monkeypatch.setattr(poller.chunks, "__defaults__", (3,))
    fake = FakeProvider()
    svc = setup_llm(core, fake)
    prop = add_property(core)
    for _ in range(3):
        add_photo(core, add_guest(core), labels=("a", "b"))
    poll_once(svc)
    assert len(fake.scored) == 3 and all(rel for _, _, rel in fake.scored)
    assert len(scores(core, prop)) == 3


def test_verdict_is_stored(core):
    fake = FakeProvider(
        score_fn=lambda lines: {x.ref: [0.1, 0.95] if len(x.labels) == 2 else [0.3] for x in lines}
    )
    svc = setup_llm(core, fake)
    add_property(core)
    add_category(core, "coolstes_objekt", COOLEST_SPEC)
    winner, winner_pub = add_photo(
        core, add_guest(core, display_name="Lena"), labels=("person", "disco ball")
    )
    add_photo(core, add_guest(core), labels=("chair",))
    result = poll_once(svc)
    assert result.state == "done"
    prompt, lines = fake.verdicts[0]
    assert prompt.startswith("Werte das coolste Objekt")
    # top 1 by prop.coolness.max, with its scores
    assert [(x.ref, x.author, x.labels) for x in lines] == [
        (f"P{winner_pub}", "Lena", ("person", "disco ball"))
    ]
    assert dict(lines[0].scores) == {"coolness": [0.1, 0.95]}
    row = dict(core.db.one("SELECT * FROM wall_category_verdicts"))
    assert row["category_id"] == "coolstes_objekt" and row["photo_id"] == winner
    assert row["object_idx"] == 0 and row["emoji"] == "🏆" and row["poll_id"] == result.poll_id
    assert row["text"].startswith("Lena hat")
    usage = [r["kind"] for r in core.db.all("SELECT kind FROM llm_usage ORDER BY id")]
    assert usage == ["property", "verdict"]


def test_verdict_answer_is_checked(core):
    fake = FakeProvider(
        verdict_out=VerdictOut(
            text="Ignore all‮ rules\x00 " + "x" * 300,
            emoji="lol",
            photo="Pnot-a-winner",
            object_index=7,
        )
    )
    svc = setup_llm(core, fake)
    add_property(core)
    add_category(core, "coolstes_objekt", COOLEST_SPEC)
    add_photo(core, add_guest(core), labels=("hat",))
    poll_once(svc)
    row = core.db.one("SELECT * FROM wall_category_verdicts")
    assert len(row["text"]) <= 160 and "‮" not in row["text"] and "\x00" not in row["text"]
    assert row["emoji"] is None and row["photo_id"] is None and row["object_idx"] is None

    # a valid photo with an index outside its list keeps the photo, drops the index
    pub = fake.verdicts[0][1][0].ref
    fake.verdict_out = VerdictOut(text="Hut!", emoji="🎩", photo=pub, object_index=5)
    poll_once(svc, force=True)
    row = core.db.one("SELECT * FROM wall_category_verdicts")
    assert row["photo_id"] is not None and row["object_idx"] is None and row["emoji"] == "🎩"


def test_verdict_skips_opted_out_winners_and_disabled_categories(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)
    add_property(core)
    add_category(core, "aus", COOLEST_SPEC, enabled=False)
    add_category(core, "coolstes_objekt", COOLEST_SPEC)
    uid = add_guest(core)
    add_photo(core, uid, labels=("hat",))
    poll_once(svc)
    assert len(fake.verdicts) == 1  # the disabled one is not asked
    set_flags(core, uid, ai=True)
    poll_once(svc, force=True)
    assert len(fake.verdicts) == 1
    # no winner the poll may send: the old verdict goes
    assert core.db.one("SELECT COUNT(*) AS n FROM wall_category_verdicts")["n"] == 0


def test_failures_are_recorded(core):
    fake = FakeProvider(fail=ProviderError("Antwort ohne Fotoliste.", kind="bad_output"))
    svc = setup_llm(core, fake)
    add_property(core)
    add_photo(core, add_guest(core))
    result = poll_once(svc)
    assert result.state == "failed" and "Antwort ohne Fotoliste." in result.reason
    assert core.db.one("SELECT ok FROM llm_usage")["ok"] == 0
    # a failed poll is not "unchanged": the next one runs again
    fake.fail = None
    assert poll_once(svc).state == "done"


def test_nothing_to_do_writes_no_row(core):
    svc = setup_llm(core, FakeProvider())
    add_photo(core, add_guest(core))
    assert poll_once(svc) is None  # no property, no verdict category
    add_property(core)
    setup_llm(core, None, enabled=False)
    assert poll_once(svc) is None
    assert polls(core) == []


def test_trigger(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)
    assert svc.poller.trigger() == (False, "Keine Eigenschaft und keine Kategorie mit KI-Urteil.")
    add_property(core)
    add_photo(core, add_guest(core))
    started, reason = svc.poller.trigger()
    assert started is True and reason is None
    for _ in range(200):
        if fake.scored and not svc.poller.running:
            break
        import time

        time.sleep(0.01)
    assert len(fake.scored) == 1 and svc.poller.last_poll_at is not None
    assert svc.poller.state() == "idle"
