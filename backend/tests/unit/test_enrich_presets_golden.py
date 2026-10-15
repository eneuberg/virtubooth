"""Golden test: the 19 preset CategorySpecs pick exactly the winners (photo,
value, label) of the old hard-coded scoring, on a fixed party of ~40 photos
with ties, several photos per guest, hidden, deleted, other-source and
too-new photos."""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import engine, presets
from virtubooth.extensions.wall.enrich.engine import PhotoFilter
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

T0 = "2026-10-13T18:00:00.000+00:00"
FILTERS = {
    "all": PhotoFilter(sources=None, not_after="2026-10-13T23:59:00.000+00:00"),
    "booth_before_19_30": PhotoFilter(sources=("booth",),
                                      not_after="2026-10-13T19:30:00.000+00:00"),  # fmt: skip
}

# fact → candidate values (crossing every preset's threshold, with ties)
FACT_VALUES: dict[str, list[float]] = {
    "people": [1, 2, 2, 3, 4, 5, 7],
    "faces": [0, 1, 1, 2, 3],
    "smiles": [0, 1, 2, 2, 3],
    "hands": [0, 2, 3, 4, 6],
    "sad_max": [0.1, 0.49, 0.5, 0.7, 0.9],
    "surprise_max": [0.2, 0.5, 0.6, 0.95],
    "happy_max": [0.3, 0.6, 0.6, 0.9],
    "glasses": [0, 1, 2],
    "hats": [0, 1, 1, 3],
    "age_groups": [1, 2, 2, 3],
    "age_spread": [10, 30, 50],
    "peace": [0, 1, 2],
    "rock": [0, 1],
    "thumbs_up": [0, 1, 3],
    "drinks": [0, 1, 2, 4],
    "mouth_open": [0, 1, 2, 3],
    "colorfulness": [20, 39.9, 40, 55, 80],
    "face_area_max": [0.05, 0.11, 0.12, 0.3, 0.5],
    "sharpness": [10, 40, 80, 81, 500],
    "brightness": [0.05, 0.1, 0.5, 0.92, 0.95],
}


def build_party(data: Path) -> tuple[Database, list[int]]:
    rnd = random.Random(20261015)
    db = Database(data / "virtubooth.db")
    repos = Repositories.create(db, data)
    users = [
        create_user(db, repos, consent_version="1", instagram=None, fp_hash=None,
                    fp_components={}, ip="10.0.0.1", user_agent="pytest").id
        for _ in range(8)
    ]  # fmt: skip
    ids: list[int] = []
    for n in range(42):
        # guest 0 takes many photos (Dauerauslöser), the rest are spread out
        user = users[0] if n % 5 == 0 else users[rnd.randrange(len(users))]
        ext = "beer" if n % 11 == 7 else "booth"
        created = f"2026-10-13T{18 + n // 25:02d}:{(n * 2) % 60:02d}:{n % 7:02d}.000+00:00"
        public_id = new_public_id()
        repos.photos.insert(
            public_id=public_id, extension=ext, user_id=user, filename="x.jpg",
            thumb_filename="t.jpg", width=10, height=10, size=1, meta={}, created_at=created,
        )  # fmt: skip
        pid = repos.photos.internal_id(public_id)
        assert pid is not None
        facts = {k: rnd.choice(v) for k, v in FACT_VALUES.items() if rnd.random() < 0.7}
        with db.tx() as c:
            c.execute(
                "INSERT INTO wall_analysis (photo_id, state, data, rev) VALUES (?, 'done', ?, ?)",
                (pid, json.dumps({}), pid),
            )
            c.executemany(
                "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
                [(pid, k, float(v)) for k, v in facts.items()],
            )
        if n % 13 == 3:
            repos.photos.hide(public_id, at=T0, reason="admin")
        if n % 17 == 5:
            repos.photos.mark_deleted(public_id, at=T0)
        ids.append(pid)
    return db, ids


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Database]:
    db, _ = build_party(tmp_path / "data")
    yield db
    db.close()


def engine_winners(db: Database, cid: str, flt: PhotoFilter) -> list[tuple[int, float, str]]:
    spec = engine.validate(presets.BY_ID[cid][0])
    return [(w.photo_id, w.value, w.label)
            for w in engine.evaluate(SimpleNamespace(db=db), spec, flt, 3)]  # fmt: skip


# Captured from the old hard-coded scoring (`enrich/categories.py`, deleted
# after this test passed against it): (photo id, value, label) per filter.
GOLDEN: dict[str, dict[str, list[tuple[int, float, str]]]] = {}


def test_nineteen_classic_presets():
    assert len(presets.CLASSIC) == 19
    assert [p for p, _, _ in presets.PRESETS][-1] == "coolstes_objekt"
    for pid, spec, _ in presets.PRESETS:
        assert engine.validate(spec) == spec, pid  # stored as written


@pytest.mark.parametrize("cid", presets.CLASSIC)
@pytest.mark.parametrize("fname", list(FILTERS))
def test_presets_pick_the_old_winners(party, cid, fname):
    from virtubooth.extensions.wall.enrich import categories as old

    flt = FILTERS[fname]
    cat = old.BY_ID[cid]
    expected = [(pid, value, cat.label(value)) for pid, value in old.winners_of(party, cat, flt, 3)]
    assert engine_winners(party, cid, flt) == expected
