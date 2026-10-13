"""The 19 Live-Wall categories: thresholds, ranking, visibility filters, labels,
availability."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from virtubooth.db.database import Database
from virtubooth.domain.models import User, new_public_id
from virtubooth.extensions.wall.enrich import categories as cats
from virtubooth.extensions.wall.enrich.analyzers import INFOS
from virtubooth.extensions.wall.enrich.categories import BY_ID, CATALOGUE, PhotoFilter
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

T0 = "2026-10-13T18:00:00.000+00:00"
LATE = "2026-10-13T23:59:00.000+00:00"
ALL = PhotoFilter(sources=None, not_after=LATE)


def at(minute: int) -> str:
    return f"2026-10-13T18:{minute:02d}:00.000+00:00"


class Party:
    def __init__(self, data: Path) -> None:
        self.db = Database(data / "virtubooth.db")
        self.repos = Repositories.create(self.db, data)
        self.users = [self.user() for _ in range(3)]
        self._minute = 0

    def user(self) -> User:
        return create_user(self.db, self.repos, consent_version="1", instagram=None,
                           fp_hash=None, fp_components={}, ip="10.0.0.1", user_agent="pytest")  # fmt: skip

    def photo(self, created_at: str | None = None, *, ext: str = "booth", user: int = 0,
              **facts: float) -> int:  # fmt: skip
        if created_at is None:
            self._minute += 1
            created_at = at(self._minute)
        public_id = new_public_id()
        self.repos.photos.insert(
            public_id=public_id, extension=ext, user_id=self.users[user].id, filename="x.jpg",
            thumb_filename="t.jpg", width=10, height=10, size=1, meta={}, created_at=created_at,
        )  # fmt: skip
        pid = self.repos.photos.internal_id(public_id)
        assert pid is not None
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO wall_analysis (photo_id, state, data, rev) VALUES (?, 'done', ?, ?)",
                (pid, json.dumps({}), pid),
            )
            c.executemany(
                "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
                [(pid, k, float(v)) for k, v in facts.items()],
            )
        return pid

    def public(self, pid: int) -> str:
        return str(self.db.one("SELECT public_id FROM photos WHERE id=?", (pid,))[0])

    def winners(self, cid: str, flt: PhotoFilter = ALL, n: int = 3) -> list[tuple[int, float]]:
        return cats.winners_of(self.db, BY_ID[cid], flt, n)


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Party]:
    p = Party(tmp_path / "data")
    yield p
    p.db.close()


def test_the_catalogue():
    ids = [c.id for c in CATALOGUE]
    assert len(ids) == len(set(ids)) == 19
    assert ids[0] == "volles_haus" and ids[-1] == "dauerausloeser"
    names = {i.name for i in INFOS}
    for c in CATALOGUE:
        assert c.emoji and c.title and c.line
        assert set(c.needs) <= names


# (category, fact, value just below the threshold, at it, label at it)
THRESHOLDS = [
    ("volles_haus", "people", 2, 3, "3 Personen"),
    ("haende_hoch", "hands", 2, 3, "3 Hände"),
    ("grinsekatzen", "smiles", 1, 2, "2 Lächeln"),
    ("herzschmerz", "sad_max", 0.49, 0.5, "50 % Drama"),
    ("ach_du_schreck", "surprise_max", 0.49, 0.5, "50 % Schreck"),
    ("brillenbande", "glasses", 0, 1, "1 Brille"),
    ("generationen", "age_groups", 1, 2, "2 Generationen"),
    ("peace", "peace", 0, 1, "1 Peace-Zeichen"),
    ("rock", "rock", 0, 1, "1 Pommesgabel"),
    ("daumen_hoch", "thumbs_up", 0, 1, "1 Daumen"),
    ("prost", "drinks", 1, 2, "2 Gläser"),
    ("hutparade", "hats", 0, 1, "1 Hut"),
    ("gesangseinlage", "mouth_open", 1, 2, "2 offene Münder"),
    ("farbexplosion", "colorfulness", 39.9, 40, "Farbwert 40"),
]


@pytest.mark.parametrize(("cid", "fact", "below", "value", "label"), THRESHOLDS)
def test_thresholds_and_labels(party, cid, fact, below, value, label):
    party.photo(**{fact: below})
    assert party.winners(cid) == []
    best = party.photo(**{fact: value + 1 if value >= 1 else value + 0.3})
    ok = party.photo(**{fact: value})
    assert [w[0] for w in party.winners(cid)] == [best, ok]
    assert BY_ID[cid].label(value) == label


def test_plural_labels():
    assert BY_ID["volles_haus"].label(1) == "1 Person"
    assert BY_ID["volles_haus"].label(7) == "7 Personen"
    assert BY_ID["herzschmerz"].label(0.823) == "82 % Drama"
    assert BY_ID["hutparade"].label(2) == "2 Hüte"
    assert BY_ID["dauerausloeser"].label(12) == "12 Fotos"
    assert BY_ID["generationen"].label(3) == "3 Generationen"
    assert BY_ID["solo_star"].label(0.34) == "34 % Gesicht"


def test_ties_go_to_the_newer_photo_and_per_category_caps(party):
    old = party.photo(people=4)
    new = party.photo(people=4)
    top = party.photo(people=9)
    assert party.winners("volles_haus") == [(top, 9.0), (new, 4.0), (old, 4.0)]
    assert party.winners("volles_haus", n=1) == [(top, 9.0)]


def test_only_visible_photos_win(party):
    shown = party.photo(people=3)
    hidden = party.photo(people=8)
    deleted = party.photo(people=9)
    other_source = party.photo(people=7, ext="beer")
    too_new = party.photo("2026-10-13T20:00:00.000+00:00", people=6)
    party.repos.photos.hide(party.public(hidden), at=T0, reason="admin")
    party.repos.photos.mark_deleted(party.public(deleted), at=T0)
    flt = PhotoFilter(sources=("booth",), not_after="2026-10-13T19:00:00.000+00:00")
    assert party.winners("volles_haus", flt) == [(shown, 3.0)]
    # no source filter: the other extension counts; an empty tuple means all too
    assert party.winners("volles_haus", PhotoFilter(None, LATE)) == [
        (other_source, 7.0), (too_new, 6.0), (shown, 3.0),
    ]  # fmt: skip
    assert party.winners("volles_haus", PhotoFilter((), LATE)) == party.winners(
        "volles_haus", PhotoFilter(None, LATE)
    )


def test_dream_team_needs_two_people_two_smiles(party):
    party.photo(people=2, smiles=1)
    party.photo(people=3, smiles=2)
    plain = party.photo(people=2, smiles=2, happy_max=0.6)
    happy = party.photo(people=2, smiles=2, happy_max=0.9)
    assert [w[0] for w in party.winners("dream_team")] == [happy, plain]
    assert BY_ID["dream_team"].label(2) == "2 Leute, 2 Lächeln"


def test_solo_star(party):
    party.photo(faces=2, face_area_max=0.5)
    party.photo(faces=1, face_area_max=0.11)
    near = party.photo(faces=1, face_area_max=0.4)
    nearish = party.photo(faces=1, face_area_max=0.12)
    assert party.winners("solo_star") == [(near, 0.4), (nearish, 0.12)]


def test_generations_rank_by_age_spread_when_fairface_ran(party):
    three = party.photo(age_groups=3)
    two_wide = party.photo(age_groups=2, age_spread=50)
    two = party.photo(age_groups=2)
    assert [w[0] for w in party.winners("generationen")] == [two_wide, three, two]


def test_action_shot_is_the_blurriest_lit_photo(party):
    party.photo(sharpness=900, brightness=0.5)  # sharp
    party.photo(sharpness=5, brightness=0.03)  # black, not action
    blurry = party.photo(sharpness=40, brightness=0.4)
    blurrier = party.photo(sharpness=12, brightness=0.6)
    assert party.winners("action_shot") == [(blurrier, 12.0), (blurry, 40.0)]
    assert BY_ID["action_shot"].label(12) == "volle Bewegung"


def test_opening_photo(party, monkeypatch):
    monkeypatch.setenv("VB_TIMEZONE", "Europe/Berlin")
    party.photo(at(30))
    first = party.photo("2026-10-13T17:42:00.000+00:00")
    hidden_earlier = party.photo("2026-10-13T17:00:00.000+00:00")
    party.repos.photos.hide(party.public(hidden_earlier), at=T0, reason="admin")
    (winner,) = party.winners("eroeffnung")  # one winner only
    assert winner[0] == first
    assert BY_ID["eroeffnung"].label(winner[1]) == "um 19:42"


def test_most_photos_of_one_guest(party):
    for _ in range(4):
        party.photo(user=1)
    for _ in range(5):
        newest = party.photo(user=2)
    assert party.winners("dauerausloeser") == [(newest, 5.0)]
    party.photo(user=1)
    last = party.photo(user=1)  # now 6: first place, shown with the newest photo
    assert party.winners("dauerausloeser") == [(last, 6.0), (newest, 5.0)]


def test_winners_of_several_in_catalogue_order(party):
    party.photo(people=3, colorfulness=80)
    out = cats.winners(party.db, ["farbexplosion", "unknown", "volles_haus", "prost"], ALL)
    assert [(w.category.id, len(w.winners)) for w in out] == [
        ("volles_haus", 1), ("prost", 0), ("farbexplosion", 1),
    ]  # fmt: skip


def test_availability():
    everything = {i.name for i in INFOS}
    assert all(c.available(everything) is None for c in CATALOGUE)
    assert BY_ID["haende_hoch"].available(everything - {"gestures"}) == (
        "Braucht die Analyse „Hände und Gesten“."
    )
    assert BY_ID["eroeffnung"].available(set()) is None
    assert BY_ID["farbexplosion"].available({"basic"}) is None


def test_opted_out_guests_never_win_by_ml_facts(party):
    a = party.photo(user=0, people=5, colorfulness=90)
    b = party.photo(user=1, people=3, colorfulness=50)
    with party.db.tx() as c:
        c.execute("UPDATE users SET analysis_opt_out=1 WHERE id=?", (party.users[0].id,))
    assert [pid for pid, _ in party.winners("volles_haus")] == [b]
    # image values (basic) still count
    assert [pid for pid, _ in party.winners("farbexplosion")] == [a, b]
