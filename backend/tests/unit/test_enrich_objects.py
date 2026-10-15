"""The frozen object list (`enrich/objects.py`, PLAN-NIGHT §4.1): append-only,
one run per source, UPDATEs abort, eligibility for external detection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from virtubooth.core.clock import now_iso
from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import jobs, objects
from virtubooth.extensions.wall.enrich.analyzers.objects import LABEL_DE, facts_of, select
from virtubooth.extensions.wall.enrich.objects import DetectedObject, FrozenError, StoredObject
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

HAT = DetectedObject("hat", "Hut", 0.9, (0.1, 0.2, 0.3, 0.4))
GLASS = DetectedObject("wine glass", "Weinglas", 0.7, None)


class Party:
    def __init__(self, data: Path) -> None:
        self.db = Database(data / "virtubooth.db")
        self.repos = Repositories.create(self.db, data)

    def user(self) -> int:
        return create_user(self.db, self.repos, consent_version="1", instagram=None,
                           fp_hash=None, fp_components={}, ip="10.0.0.1",
                           user_agent="pytest").id  # fmt: skip

    def photo(
        self, user_id: int | None = None, *, state: str | None = "done", ai: bool = True
    ) -> int:
        public_id = new_public_id()
        self.repos.photos.insert(
            public_id=public_id, extension="booth", user_id=user_id or self.user(),
            filename="x.jpg", thumb_filename="t.jpg", width=10, height=10, size=1, meta={},
            created_at=now_iso(),
        )  # fmt: skip
        pid = self.repos.photos.internal_id(public_id)
        assert pid is not None
        if state:
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO wall_analysis (photo_id, state, rev, ai_detect) VALUES "
                    "(?, ?, (SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis), ?)",
                    (pid, state, int(ai)),
                )
        return pid

    def rev(self, pid: int) -> int:
        return int(self.db.one("SELECT rev FROM wall_analysis WHERE photo_id=?", (pid,))[0])


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Party]:
    p = Party(tmp_path / "data")
    yield p
    p.db.close()


def test_append_continues_the_idx_and_bumps_the_rev(party):
    pid = party.photo()
    rev = party.rev(pid)
    assert objects.append(party.db, pid, "local", "efficientdet_lite2@2", [HAT, GLASS]) == [0, 1]
    assert party.rev(pid) > rev
    rev = party.rev(pid)
    claude = DetectedObject("party hat", "Partyhut", 0.95, (0.5, 0.5, 0.2, 0.2))
    assert objects.append(party.db, pid, "claude", "claude-haiku-5-5", [claude]) == [2]
    assert party.rev(pid) > rev
    listed = objects.objects_of(party.db, [pid, 999])
    assert list(listed) == [pid]
    assert listed[pid] == [
        StoredObject("hat", "Hut", 0.9, (0.1, 0.2, 0.3, 0.4), 0, "local", "efficientdet_lite2@2",
                     ("local",)),
        StoredObject("wine glass", "Weinglas", 0.7, None, 1, "local", "efficientdet_lite2@2",
                     ("local",)),
        StoredObject("party hat", "Partyhut", 0.95, (0.5, 0.5, 0.2, 0.2), 2, "claude",
                     "claude-haiku-5-5", ("claude",)),
    ]  # fmt: skip
    runs = objects.runs_of(party.db, pid)
    assert [(r["source"], r["state"], r["objects"]) for r in runs] == [
        ("local", "done", 2), ("claude", "done", 1),
    ]  # fmt: skip


def test_a_source_runs_once_per_photo(party):
    pid = party.photo()
    objects.append(party.db, pid, "local", "m@1", [HAT])
    with pytest.raises(FrozenError):
        objects.append(party.db, pid, "local", "m@1", [GLASS])
    with pytest.raises(FrozenError):
        objects.record_run(party.db, pid, "local", "failed", None, "x")
    objects.record_run(party.db, pid, "claude", "failed", "claude-haiku-5-5", "timeout " * 40)
    with pytest.raises(FrozenError):
        objects.append(party.db, pid, "claude", "claude-haiku-5-5", [GLASS])
    run = objects.runs_of(party.db, pid)[1]
    assert run["state"] == "failed" and len(str(run["error"])) == 200
    # nothing changed by the refused calls
    assert [o.label for o in objects.objects_of(party.db, [pid])[pid]] == ["hat"]
    with pytest.raises(ValueError):
        objects.record_run(party.db, pid, "mistral", "running", None, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE photo_objects SET label='x'",
        "UPDATE photo_objects SET score=1",
        "UPDATE photo_detection_runs SET state='failed'",
        "UPDATE wall_facts SET value=0",
    ],
)
def test_updates_abort(party, sql):
    pid = party.photo()
    objects.append(party.db, pid, "local", "m@1", [HAT])
    with party.db.tx() as c:
        c.execute("INSERT INTO wall_facts (photo_id, key, value) VALUES (?, 'faces', 1)", (pid,))
    with pytest.raises(sqlite3.IntegrityError, match="frozen"), party.db.tx() as c:
        c.execute(sql)
    assert objects.objects_of(party.db, [pid])[pid][0].label == "hat"


def test_scores_and_boxes_are_clipped(party):
    pid = party.photo()
    odd = DetectedObject("cake", "Kuchen", 1.4, (-0.1, 0.5, 1.2, 0.4))
    objects.append(party.db, pid, "claude", "c", [odd])
    (stored,) = objects.objects_of(party.db, [pid])[pid]
    assert stored.score == 1.0 and stored.box == (0.0, 0.5, 1.0, 0.4)


def test_eligible_for_external(party):
    ok_old = party.photo()
    ok_new = party.photo()
    party.photo(state="failed")  # the pipeline never finished it: never queued
    party.photo(ai=False)  # finished while the local detector was active: never sent
    party.photo(state="pending")  # local not finished
    party.photo(state=None)  # never claimed
    hidden = party.photo()
    party.repos.photos.hide(
        party.db.one("SELECT public_id FROM photos WHERE id=?", (hidden,))[0], at=now_iso(),
        reason="admin",
    )  # fmt: skip
    opted = party.user()
    party.photo(opted)
    no_ai = party.user()
    party.photo(no_ai)
    with party.db.tx() as c:
        c.execute("UPDATE users SET analysis_opt_out=1 WHERE id=?", (opted,))
        c.execute("UPDATE users SET ai_opt_out=1 WHERE id=?", (no_ai,))
    assert objects.eligible_for_external(party.db, "claude", 10) == [ok_new, ok_old]
    assert objects.eligible_for_external(party.db, "claude", 1) == [ok_new]
    objects.append(party.db, ok_new, "claude", "c", [])
    assert objects.eligible_for_external(party.db, "claude", 10) == [ok_old]
    # one AI list per photo: another provider does not look at it again
    assert ok_new not in objects.eligible_for_external(party.db, "mistral", 10)
    assert objects.count_eligible_for_external(party.db, "mistral") == 1


def test_finish_writes_the_local_list_in_its_transaction(party):
    pid = party.photo(state="pending")
    jobs.claim(party.db)

    class Boom(Exception):
        pass

    with pytest.raises(Boom), party.db.tx():
        jobs.finish(party.db, pid, facts={"people": 1}, data={}, versions={},
                    objects_found=[HAT], objects_model="m@1")  # fmt: skip
        raise Boom
    # rolled back together: nothing frozen yet, the photo can still finish
    assert objects.objects_of(party.db, [pid]) == {}
    assert jobs.facts(party.db, pid) == {}
    assert jobs.finish(party.db, pid, facts={"people": 1}, data={}, versions={},
                       objects_found=[HAT], objects_model="m@1")  # fmt: skip
    assert [o.idx for o in objects.objects_of(party.db, [pid])[pid]] == [0]


def test_detector_labels_settings_and_facts():
    assert len(LABEL_DE) == 80 and LABEL_DE["wine glass"] == "Weinglas"
    found = [
        DetectedObject("person", "Person", 0.9, None),
        DetectedObject("person", "Person", 0.38, None),  # counted as object, not as a person
        DetectedObject("cup", "Becher", 0.5, None),
        DetectedObject("cell phone", "Handy", 0.2, None),
    ]
    kept = select(found, {"score_min": 0.3, "max_objects": 3})
    assert [o.score for o in kept] == [0.9, 0.5, 0.38]
    assert facts_of(kept, faces=0) == {"people": 1.0, "drinks": 1.0, "phones": 0.0}
    assert facts_of(kept, faces=4)["people"] == 4.0
    assert len(select(found, None)) == 3  # defaults: score ≥ 0.35
