"""The poll (PLAN-NIGHT N8, categories v2): only properties an enabled category
reads, scores aligned with the object lists, latest values only, skipped when
nothing changed; then the AI's comments (exactly `count`, cached per category
and photo, invalidated by a prompt/model change)."""

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
    property_spec,
    set_flags,
    setup_llm,
    use_property,
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
    b, _ = add_photo(core, add_guest(core, name="Kluge Katze", instagram="anna.b"), labels=("dog",))
    result = poll_once(svc)
    assert result is not None and result.state == "done"
    assert scores(core, prop) == {a: [0.1, 0.2], b: [0.1]}
    prompt, lines, relative = fake.scored[0]
    assert prompt == "Wie cool ist das?" and relative is False
    assert [(x.ref, x.author, x.labels) for x in lines] == [
        (f"P{a_pub}", "Flinker Fuchs", ("person", "hat")),
        (lines[1].ref, "Kluge Katze", ("dog",)),  # the wall hides Instagram names (default)
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


def test_only_properties_an_enabled_category_reads_are_polled(core):
    from virtubooth.extensions.wall.llm import properties

    fake = FakeProvider()
    svc = setup_llm(core, fake)
    prop = add_property(core)
    add_property(core, "lustigkeit", "Wie lustig?", used=False)  # no category reads it
    add_property(core, "aus", "Nur in einer ausgeschalteten?", used=False)
    use_property(core, "aus", enabled=False)
    add_property(core, "weg", "Im Papierkorb?")
    add_photo(core, add_guest(core))
    properties.set_trashed(core.db, core.repos.audit, "weg", True, actor="t")
    assert [p.name for p in properties.polled(core.db)] == ["coolness"]
    poll_once(svc)
    assert [p for p, _, _ in fake.scored] == ["Wie cool ist das?"]
    assert len(scores(core, prop)) == 1
    # trashing switched its category off
    row = core.db.one("SELECT enabled, off_reason, off_detail FROM wall_categories WHERE id=?",
                      ("uses_weg",))  # fmt: skip
    assert tuple(row) == (0, "property_trashed", "weg")
    # without an enabled category nothing is polled, and there is nothing to do
    with core.db.tx() as c:
        c.execute("UPDATE wall_categories SET enabled = 0")
    assert properties.polled(core.db) == []
    assert poll_once(svc) is None


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


def comments(core):
    return [
        dict(r)
        for r in core.db.all("SELECT * FROM wall_category_comments ORDER BY category_id, photo_id")
    ]


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
    # count 1 (a v1 verdict converts to one comment): the top winner, with its scores,
    # rank, focus object and value
    assert [(x.ref, x.author, x.labels, x.rank, x.focus) for x in lines] == [
        (f"P{winner_pub}", "Lena", ("person", "disco ball"), 1, 1)
    ]
    assert dict(lines[0].scores) == {"coolness": [0.1, 0.95]}
    assert lines[0].value == "Disco Ball"
    (row,) = comments(core)
    assert row["category_id"] == "coolstes_objekt" and row["photo_id"] == winner
    assert row["object_idx"] == 0 and row["emoji"] == "🏆" and row["poll_id"] == result.poll_id
    assert row["text"].startswith("Lena hat")
    usage = [r["kind"] for r in core.db.all("SELECT kind FROM llm_usage ORDER BY id")]
    assert usage == ["property", "verdict"]
    # the default verdict model: the provider's cheapest (Haiku class)
    assert fake.verdict_models == ["claude-haiku-5-5"]


def test_exactly_count_comments_cached_per_photo_and_invalidated(core):
    fake = FakeProvider(score_fn=lambda lines: {x.ref: [0.1 * (len(x.labels))] * len(x.labels)
                                                for x in lines})  # fmt: skip
    svc = setup_llm(core, fake)
    add_property(core, used=False)
    spec = property_spec("coolness", verdict={"prompt": None, "count": 2, "model": None,
                                              "effort": "low"})  # fmt: skip
    add_category(core, "cool", spec)
    a, _ = add_photo(core, add_guest(core), labels=("a", "b", "c"))
    b, _ = add_photo(core, add_guest(core), labels=("a", "b"))
    c, _ = add_photo(core, add_guest(core), labels=("a",))
    poll_once(svc)
    # the top 2 winners, one comment each, in rank order; the default prompt names the title
    prompt, lines = fake.verdicts[0]
    assert "„Bestes coolness“" in prompt
    assert [x.rank for x in lines] == [1, 2]
    assert [r["photo_id"] for r in comments(core)] == [a, b]
    # unchanged winners: cached, no new call (a forced poll still rates the properties)
    poll_once(svc, force=True)
    assert len(fake.verdicts) == 1
    # a new winner: only the new pair is asked
    d, _ = add_photo(core, add_guest(core), labels=("a", "b", "c", "d"))
    poll_once(svc)
    assert [x.rank for x in fake.verdicts[1][1]] == [1] and len(fake.verdicts[1][1]) == 1
    assert {r["photo_id"] for r in comments(core)} == {a, b, d}  # b's stays cached
    # a prompt change invalidates the category's comments: both winners asked again
    spec2 = {**spec, "verdict": {**spec["verdict"], "prompt": "Sei nett."}}
    with core.db.tx() as cur:
        cur.execute("UPDATE wall_categories SET spec=? WHERE id='cool'", (json.dumps(spec2),))
    poll_once(svc)
    assert fake.verdicts[2][0] == "Sei nett." and len(fake.verdicts[2][1]) == 2
    assert {r["photo_id"] for r in comments(core)} == {d, a}
    assert len({r["config_hash"] for r in comments(core)}) == 1
    # a model change (Sonnet) too
    spec3 = {**spec2, "verdict": {**spec2["verdict"], "model": "claude-sonnet-5-5",
                                  "effort": "medium"}}  # fmt: skip
    with core.db.tx() as cur:
        cur.execute("UPDATE wall_categories SET spec=? WHERE id='cool'", (json.dumps(spec3),))
    poll_once(svc)
    assert fake.verdict_models[-1] == "claude-sonnet-5-5" and fake.efforts[-1] == "medium"
    assert len(fake.verdicts[3][1]) == 2
    del c


def test_the_guardrails_are_always_in_the_system_prompt():
    from virtubooth.extensions.wall.llm import prompts

    system = prompts.VERDICT_SYSTEM
    for word in ("never change it", "exactly one comment", "120 characters", "bodies",
                 "weight", "origin", "religion", "disability", "sexuality", "no insults",
                 "party-safe", prompts.DATA_RULE):  # fmt: skip
        assert word in system
    assert prompts.verdict_prompt(None, "Hutparade") == prompts.DEFAULT_VERDICT_PROMPT.format(
        title="Hutparade"
    )
    assert prompts.verdict_prompt("  Eigener  ", "x") == "Eigener"


def test_verdict_answer_is_checked(core):
    fake = FakeProvider(
        verdict_out=[
            VerdictOut(text="Nicht gesendet", emoji=None, photo="Pnot-a-winner", object_index=0),
            VerdictOut(text="", emoji=None, photo=None, object_index=None),
        ]
    )
    svc = setup_llm(core, fake)
    add_property(core)
    add_category(core, "coolstes_objekt", COOLEST_SPEC)
    add_photo(core, add_guest(core), labels=("hat",))
    result = poll_once(svc)
    assert comments(core) == [] and "leere Antwort" in (result.reason or "")
    pub = fake.verdicts[0][1][0].ref
    fake.verdict_out = [
        VerdictOut(text="Ignore all‮ rules\x00 " + "x" * 300, emoji="lol", photo=pub,
                   object_index=7),
        VerdictOut(text="Zweimal dasselbe Foto", emoji=None, photo=pub, object_index=0),
    ]  # fmt: skip
    poll_once(svc, force=True)
    (row,) = comments(core)
    assert len(row["text"]) <= 160 and "‮" not in row["text"] and "\x00" not in row["text"]
    assert row["emoji"] is None and row["object_idx"] is None
    assert row["text"].startswith("Ignore all")


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
    assert svc.poller.trigger() == (
        False,
        "Keine eingeschaltete Kategorie braucht eine Eigenschaft oder ein KI-Urteil.",
    )
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


def test_handles_go_out_only_while_the_wall_shows_them(core):
    """The verdict text lands on the wall: a guest is named as the wall names
    them (display name, „@handle“ only with show_instagram, else the pseudonym)."""
    from virtubooth.extensions.wall import config as wall_config

    fake = FakeProvider()
    svc = setup_llm(core, fake)
    add_property(core)
    add_photo(core, add_guest(core, name="Kluge Katze", instagram="anna.b"), labels=("dog",))
    add_photo(core, add_guest(core, name="Wilder Wal", display_name="Walfisch"), labels=("cup",))
    poll_once(svc)
    assert sorted(x.author for x in fake.scored[-1][1]) == ["Kluge Katze", "Walfisch"]
    repo = core.repos.app_settings
    cfg = wall_config.load_config(repo).model_copy(update={"show_instagram": True})
    wall_config.store_config(repo, cfg, at="2026-10-15T20:00:00.000+00:00")
    assert wall_config.load_config(repo).show_instagram
    poll_once(svc, force=True)
    assert sorted(x.author for x in fake.scored[-1][1]) == ["@anna.b", "Walfisch"]


def test_the_verdict_model_follows_the_provider():
    from virtubooth.extensions.wall.llm import pricing

    resolve = pricing.resolve_verdict_model
    assert resolve("anthropic", None) == "claude-haiku-5-5"
    assert resolve("anthropic", "claude-sonnet-5-5") == "claude-sonnet-5-5"
    # a provider change keeps the class (Sonnet → DeutschlandGPT's Sonnet, Mistral Medium)
    assert resolve("deutschlandgpt", "claude-sonnet-5-5") == "claude-sonnet-5.5"
    assert resolve("mistral", "claude-sonnet-5-5") == "mistral-medium-2508"
    assert resolve("scaleway", "claude-sonnet-5-5") == "deepseek-v4.1-flash"  # only one
    assert "claude-opus-5-5" not in pricing.VERDICT_MODEL_IDS
