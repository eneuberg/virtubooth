"""Each source's own object list and the merged list (migration 14,
`enrich/merge.py`, `enrich/objects.py`): duplicates link, the rest is appended,
idx never moves, everything frozen; a v13 database splits its rows by source."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from virtubooth.core.clock import now_iso
from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import merge, objects
from virtubooth.extensions.wall.enrich.objects import DetectedObject as D
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

LOCAL_M = "efficientdet_lite2@2"
AI_M = "claude-haiku-5-5"
PERSON = D("person", "Person", 0.9, (0.1, 0.1, 0.3, 0.8))
GLASS = D("wine glass", "Weinglas", 0.6, (0.5, 0.5, 0.1, 0.2))
CUP = D("cup", "Becher", 0.4, (0.8, 0.1, 0.1, 0.1))


class Party:
    def __init__(self, path: Path) -> None:
        self.db = Database(path / "virtubooth.db")
        self.repos = Repositories.create(self.db, path)
        self.uid = create_user(self.db, self.repos, consent_version="1", instagram=None,
                               fp_hash=None, fp_components={}, ip="10.0.0.1",
                               user_agent="pytest").id  # fmt: skip

    def photo(self) -> int:
        public_id = new_public_id()
        self.repos.photos.insert(
            public_id=public_id, extension="booth", user_id=self.uid, filename="x.jpg",
            thumb_filename="t.jpg", width=10, height=10, size=1, meta={}, created_at=now_iso(),
        )  # fmt: skip
        pid = self.repos.photos.internal_id(public_id)
        assert pid is not None
        return pid

    def merged(self, pid: int) -> list[tuple[int, str, tuple[str, ...]]]:
        return [(o.idx, o.label, o.sources) for o in objects.objects_of(self.db, [pid])[pid]]


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Party]:
    p = Party(tmp_path)
    yield p
    p.db.close()


# ----------------------------------------------------------------- pure merge


def test_labels_map_to_coco_in_english_and_german():
    assert merge.coco_label("Smartphones") == "cell phone"
    assert merge.coco_label("glass of wine") == "wine glass"
    assert merge.coco_label("woman") == "person"
    assert merge.coco_label("champagne thing", "Sektglas") == "wine glass"
    assert merge.coco_label("bottles") == "bottle"
    assert merge.coco_label("sunglasses", "Sonnenbrille") is None
    assert merge.canonical("Mobile Phone", "Handy") == ("cell phone", "Handy")
    assert merge.canonical("party hat", "") == ("party hat", "party hat")
    assert merge.same_thing(("man", "Mann"), ("person", "Person"))
    assert merge.same_thing(("party hats", ""), ("party hat", "Partyhut"))
    assert not merge.same_thing(("cup", "Becher"), ("wine glass", "Weinglas"))


def test_plan_links_overlapping_duplicates_one_to_one():
    entries = [
        merge.Entry(0, "person", "Person", (0.1, 0.1, 0.3, 0.8), frozenset({"local"})),
        merge.Entry(1, "person", "Person", (0.6, 0.1, 0.3, 0.8), frozenset({"local"})),
        merge.Entry(2, "cup", "Becher", (0.8, 0.1, 0.1, 0.1), frozenset({"local"})),
    ]
    new = [
        D("woman", "Frau", 0.95, (0.62, 0.12, 0.28, 0.75)),  # the right person
        D("man", "Mann", 0.9, (0.12, 0.1, 0.3, 0.8)),  # the left one
        D("person", "Person", 0.5, (0.4, 0.0, 0.1, 0.1)),  # nobody there locally
        D("wine glass", "Weinglas", 0.8, (0.8, 0.1, 0.1, 0.1)),  # where the cup is: no
        D("cup", "Becher", 0.8, (0.0, 0.9, 0.05, 0.05)),  # another cup, elsewhere
    ]
    assert merge.plan(entries, new, "claude") == [1, 0, None, None, None]
    # an entry this source already has is never linked again
    taken = [merge.Entry(0, "person", "Person", (0.1, 0.1, 0.3, 0.8), frozenset({"claude"}))]
    assert merge.plan(taken, [D("person", "Person", 0.9, (0.1, 0.1, 0.3, 0.8))], "claude") == [None]


def test_plan_without_frames():
    entries = [
        merge.Entry(0, "hat", "Hut", None, frozenset({"local"})),
        merge.Entry(1, "person", "Person", (0.1, 0.1, 0.3, 0.8), frozenset({"local"})),
    ]
    # frameless: links to a frameless entry of its kind, never to a framed one
    new = [D("hat", "Hut", 0.5, None), D("person", "Person", 0.5, None)]
    assert merge.plan(entries, new, "claude") == [0, None]


def test_merge_lists_is_deterministic():
    lists = [("local", [PERSON, CUP]), ("claude", [D("cups", "Becher", 0.7, CUP.box), GLASS])]
    first = merge.merge_lists(lists)
    assert first == merge.merge_lists(lists)
    assert [(m.idx, m.label, m.parts) for m in first] == [
        (0, "person", {"local": 0}),
        (1, "cup", {"local": 1, "claude": 0}),
        (2, "wine glass", {"claude": 1}),
    ]


# ------------------------------------------------------------------- database


def test_ai_after_local_links_or_appends_and_keeps_every_idx(party):
    pid = party.photo()
    assert objects.append(party.db, pid, "local", LOCAL_M, [PERSON, GLASS]) == [0, 1]
    ai = [
        D("glass of wine", "Sektglas", 0.8, (0.51, 0.5, 0.1, 0.2)),  # = local idx 1
        D("smartphone", "Smartphone", 0.7, (0.3, 0.3, 0.05, 0.1)),  # new
        D("man", "Mann", 0.95, (0.1, 0.12, 0.3, 0.78)),  # = local idx 0
    ]
    assert objects.append(party.db, pid, "claude", AI_M, ai) == [1, 2, 0]
    assert party.merged(pid) == [
        (0, "person", ("local", "claude")),
        (1, "wine glass", ("local", "claude")),
        (2, "cell phone", ("claude",)),
    ]
    merged = objects.objects_of(party.db, [pid])[pid]
    # an appended AI object: its label in the COCO set, its own German name
    assert (merged[2].label_de, merged[2].source, merged[2].model) == ("Smartphone", "claude", AI_M)
    # a linked entry keeps the local values (frozen), the AI's stay in its own list
    assert merged[1].score == 0.6 and merged[1].box == GLASS.box
    lists = objects.source_objects_of(party.db, pid)
    assert [(o.pos, o.label, o.merged_idx) for o in lists["local"]] == [
        (0, "person", 0),
        (1, "wine glass", 1),
    ]
    assert [(o.pos, o.label, o.label_de, o.score, o.merged_idx) for o in lists["claude"]] == [
        (0, "glass of wine", "Sektglas", 0.8, 1),
        (1, "smartphone", "Smartphone", 0.7, 2),
        (2, "man", "Mann", 0.95, 0),
    ]


def test_ai_first_then_local_appends_after_the_ai_entries(party):
    """Local after the AI (the detector switched on later): the idx the AI's
    entries have stay, the local duplicates link to them."""
    pid = party.photo()
    assert objects.append(party.db, pid, "claude", AI_M, [D("lady", "Dame", 0.9, PERSON.box)]) == [
        0
    ]
    assert objects.append(party.db, pid, "local", LOCAL_M, [CUP, PERSON]) == [1, 0]
    assert party.merged(pid) == [(0, "person", ("claude", "local")), (1, "cup", ("local",))]


def test_lists_are_frozen_and_the_merged_list_append_only(party):
    pid = party.photo()
    objects.append(party.db, pid, "local", LOCAL_M, [PERSON])
    with pytest.raises(objects.FrozenError):
        objects.append(party.db, pid, "local", LOCAL_M, [CUP])
    with party.db.tx() as c, pytest.raises(sqlite3.IntegrityError, match="frozen"):
        c.execute("UPDATE photo_source_objects SET merged_idx = 5")
    with party.db.tx() as c, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute(
            "INSERT INTO photo_objects (photo_id, idx, label, label_de, score, source, model, "
            "created_at) VALUES (?, 7, 'cup', 'Becher', 1, 'local', 'm', 'x')",
            (pid,),
        )
    with party.db.tx() as c, pytest.raises(sqlite3.IntegrityError, match="links to an entry"):
        c.execute(
            "INSERT INTO photo_source_objects (photo_id, source, pos, label, label_de, score, "
            "model, merged_idx, created_at) VALUES (?, 'mistral', 0, 'cup', 'Becher', 1, 'm', "
            "3, 'x')",
            (pid,),
        )
    with party.db.tx() as c, pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        # one object per source and entry
        c.execute(
            "INSERT INTO photo_source_objects (photo_id, source, pos, label, label_de, score, "
            "model, merged_idx, created_at) VALUES (?, 'local', 1, 'person', 'Person', 1, 'm', "
            "0, 'x')",
            (pid,),
        )
    assert party.merged(pid) == [(0, "person", ("local",))]


def test_purge_drops_the_source_lists_of_deleted_photos(party):
    from virtubooth.extensions.wall.enrich import jobs

    pid = party.photo()
    objects.append(party.db, pid, "local", LOCAL_M, [PERSON])
    with party.db.tx() as c:
        c.execute("INSERT INTO wall_analysis (photo_id, state, rev) VALUES (?, 'done', 1)", (pid,))
        c.execute("UPDATE photos SET deleted_at = ? WHERE id = ?", (now_iso(), pid))
    jobs.purge_deleted(party.db)
    assert party.db.one("SELECT COUNT(*) FROM photo_source_objects")[0] == 0
    assert party.db.one("SELECT COUNT(*) FROM photo_objects")[0] == 0


# ------------------------------------------------------------------ migration


def test_v14_splits_existing_objects_by_source_and_keeps_the_idx(tmp_path, monkeypatch):
    """A v13 database: every row of its (unmerged) list becomes its own merged
    entry, linked from a row of its source's list; positions count per source."""
    path = tmp_path / "virtubooth.db"
    monkeypatch.setattr(dbmod, "MIGRATIONS", tuple(m for m in dbmod.MIGRATIONS if m[0] <= 13))
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 13)
    party = Party(tmp_path)
    a, b = party.photo(), party.photo()
    rows = [
        (a, 0, "person", "Person", 0.9, 0.1, 0.1, 0.3, 0.8, "local", LOCAL_M),
        (a, 1, "cup", "Becher", 0.5, None, None, None, None, "local", LOCAL_M),
        (a, 2, "person", "Person", 0.8, 0.1, 0.1, 0.3, 0.8, "claude", AI_M),  # a duplicate then
        (a, 3, "hat", "Hut", 0.7, 0.2, 0.0, 0.2, 0.1, "claude", AI_M),
        (b, 0, "dog", "Hund", 0.6, 0.0, 0.0, 0.5, 0.5, "mistral", "mistral-small"),
    ]
    with party.db.tx() as c:
        c.executemany(
            "INSERT INTO photo_objects VALUES (?,?,?,?,?,?,?,?,?,?,?,'2026-10-10T20:00:00Z')", rows
        )
        c.execute("INSERT INTO llm_properties (id, name, prompt, created_at) VALUES (1, 'cool', "
                  "'?', 'x')")  # fmt: skip
        c.execute("INSERT INTO property_scores VALUES (1, ?, '[0.1, 0.2, 0.3, 0.4]', 1, 'x')", (a,))
    party.db.close()
    monkeypatch.undo()

    party.db = Database(path)
    assert party.db.one("PRAGMA user_version")[0] == dbmod.SCHEMA_VERSION == 14
    # the merged list is the old list, untouched
    assert (
        party.db.all("SELECT * FROM photo_objects ORDER BY photo_id, idx")
        and [
            tuple(r)[:11]
            for r in party.db.all("SELECT * FROM photo_objects ORDER BY photo_id, idx")
        ]
        == rows
    )
    assert party.merged(a) == [
        (0, "person", ("local",)),
        (1, "cup", ("local",)),
        (2, "person", ("claude",)),
        (3, "hat", ("claude",)),
    ]
    got = [
        tuple(r)
        for r in party.db.all(
            "SELECT photo_id, source, pos, label, merged_idx, model FROM photo_source_objects "
            "ORDER BY photo_id, source, pos"
        )
    ]
    assert got == [
        (a, "claude", 0, "person", 2, AI_M),
        (a, "claude", 1, "hat", 3, AI_M),
        (a, "local", 0, "person", 0, LOCAL_M),
        (a, "local", 1, "cup", 1, LOCAL_M),
        (b, "mistral", 0, "dog", 0, "mistral-small"),
    ]
    # the property scores still index the same objects
    assert party.db.one("SELECT scores FROM property_scores WHERE photo_id=?", (a,))[0] == (
        "[0.1, 0.2, 0.3, 0.4]"
    )
    # the triggers work on the upgraded database too
    with party.db.tx() as c, pytest.raises(sqlite3.IntegrityError, match="frozen"):
        c.execute("UPDATE photo_source_objects SET label = 'x'")
    # a new source on an old photo merges with the rows that were there
    assert objects.append(party.db, b, "local", LOCAL_M, [D("dog", "Hund", 0.9, (0, 0, 0.5, 0.5))])
    assert party.merged(b) == [(0, "dog", ("mistral", "local"))]
    party.db.close()
