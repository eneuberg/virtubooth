"""Live-Wall analysis jobs (`wall_analysis`, `wall_facts`): newest first, retries,
crash recovery, rerun, purge of deleted photos, the global rev counter."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from virtubooth.core.clock import now_iso
from virtubooth.db.database import Database
from virtubooth.domain.models import Photo, new_public_id
from virtubooth.extensions.wall.enrich import jobs
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user


class Party:
    def __init__(self, data: Path) -> None:
        self.data = data
        self.db = Database(data / "virtubooth.db")
        self.repos = Repositories.create(self.db, data)
        self.user = create_user(
            self.db, self.repos, consent_version="1", instagram=None, fp_hash=None,
            fp_components={}, ip="10.0.0.1", user_agent="pytest",
        )  # fmt: skip

    def photo(self) -> Photo:
        public_id = new_public_id()
        self.repos.photos.insert(
            public_id=public_id, extension="booth", user_id=self.user.id,
            filename=f"{public_id}.jpg", thumb_filename=f"thumbs/{public_id}.jpg",
            width=100, height=100, size=1, meta={}, created_at=now_iso(),
        )  # fmt: skip
        photo = self.repos.photos.get(public_id)
        assert photo is not None
        return photo

    def rev(self) -> int:
        return int(self.db.one("SELECT COALESCE(MAX(rev), 0) FROM wall_analysis")[0])


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Party]:
    p = Party(tmp_path / "data")
    yield p
    p.db.close()


def test_claims_the_newest_photo_first(party):
    a, b, c = party.photo(), party.photo(), party.photo()
    order = [jobs.claim(party.db).id for _ in range(3)]
    assert order == [c.id, b.id, a.id]
    assert jobs.claim(party.db) is None
    row = jobs.get(party.db, c.id)
    assert row.state == "running" and row.attempts == 1 and row.started_at
    assert jobs.counts(party.db) == {
        "pending": 0, "running": 3, "done": 0, "failed": 0, "skipped": 0, "total": 3,
    }  # fmt: skip


def test_finish_replaces_facts_and_stores_data(party):
    p = party.photo()
    claimed = jobs.claim(party.db)
    assert claimed.public_id == p.public_id and claimed.user_name
    data = {"boxes": [], "details": [{"label": "Gast", "value": "x"}]}
    assert jobs.finish(party.db, p.id, facts={"faces": 2, "smiles": 1}, data=data,
                       versions={"basic": "1"})  # fmt: skip
    row = jobs.get(party.db, p.id)
    assert (row.state, row.error, row.versions, row.data) == ("done", None, {"basic": "1"}, data)
    assert jobs.facts(party.db, p.id) == {"faces": 2.0, "smiles": 1.0}
    # analysed again: the old facts are gone
    jobs.request(party.db, p.id)
    jobs.claim(party.db)
    jobs.finish(party.db, p.id, facts={"faces": 1}, data={}, versions={})
    assert jobs.facts(party.db, p.id) == {"faces": 1.0}


def test_failure_retries_once_then_fails(party):
    p = party.photo()
    jobs.claim(party.db)
    assert jobs.fail(party.db, p.id, "Analyse fehlgeschlagen (ValueError)") == "pending"
    assert jobs.claim(party.db).id == p.id
    assert jobs.get(party.db, p.id).attempts == 2
    assert jobs.fail(party.db, p.id, "Analyse fehlgeschlagen (ValueError)") == "failed"
    row = jobs.get(party.db, p.id)
    assert row.state == "failed" and row.error == "Analyse fehlgeschlagen (ValueError)"
    assert jobs.claim(party.db) is None


def test_crash_recovery(party):
    first, second = party.photo(), party.photo()
    jobs.claim(party.db)  # second, attempt 1
    jobs.claim(party.db)  # first
    jobs.fail(party.db, first.id, "x")
    jobs.claim(party.db)  # first, attempt 2
    # the worker died: both are still running
    assert jobs.recover_stale(party.db) == 2
    assert jobs.get(party.db, second.id).state == "pending"
    row = jobs.get(party.db, first.id)
    assert (row.state, row.error) == ("failed", jobs.ABORTED)


def test_rerun_failed_all_and_one(party):
    a, b, c = party.photo(), party.photo(), party.photo()
    for _ in range(3):
        jobs.claim(party.db)
    jobs.finish(party.db, c.id, facts={"faces": 1}, data={}, versions={})
    jobs.skip(party.db, b.id, "Fotodatei fehlt")
    jobs.fail(party.db, a.id, "x")
    jobs.claim(party.db)
    jobs.fail(party.db, a.id, "x")
    assert jobs.rerun(party.db, "failed") == 1
    row = jobs.get(party.db, a.id)
    assert (row.state, row.attempts, row.error) == ("pending", 0, None)
    assert jobs.rerun(party.db, "all") == 2  # done + skipped (a is pending already)
    assert {jobs.get(party.db, p.id).state for p in (a, b, c)} == {"pending"}
    # facts stay until the new analysis replaces them
    assert jobs.facts(party.db, c.id) == {"faces": 1.0}


def test_finish_after_a_rerun_request_is_dropped(party):
    p = party.photo()
    jobs.claim(party.db)
    jobs.request(party.db, p.id)  # admin: „Neu analysieren“ while it runs
    assert not jobs.finish(party.db, p.id, facts={"faces": 3}, data={}, versions={})
    assert jobs.get(party.db, p.id).state == "pending"
    assert jobs.facts(party.db, p.id) == {}


def test_every_write_bumps_the_rev(party):
    a, b = party.photo(), party.photo()
    revs = []
    jobs.claim(party.db)
    revs.append(party.rev())
    jobs.claim(party.db)
    revs.append(party.rev())
    jobs.finish(party.db, b.id, facts={}, data={}, versions={})
    revs.append(jobs.get(party.db, b.id).rev)
    jobs.fail(party.db, a.id, "x")
    revs.append(jobs.get(party.db, a.id).rev)
    assert revs == sorted(set(revs)) and len(revs) == 4
    # a bulk rerun gives every row its own rev
    jobs.claim(party.db)
    jobs.finish(party.db, a.id, facts={}, data={}, versions={})
    before = party.rev()
    assert jobs.rerun(party.db, "all") == 2
    assert {jobs.get(party.db, p.id).rev for p in (a, b)} == {before + 1, before + 2}


def test_purge_drops_deleted_photos(party):
    a, b = party.photo(), party.photo()
    for p in (b, a):
        jobs.claim(party.db)
        jobs.finish(party.db, p.id, facts={"faces": 1}, data={"boxes": [1]}, versions={"x": "1"})
    # a holds the highest rev: its row stays (emptied) until a later write
    party.repos.photos.mark_deleted(a.public_id, at=now_iso())
    party.repos.photos.mark_deleted(b.public_id, at=now_iso())
    jobs.purge_deleted(party.db)
    assert jobs.get(party.db, b.id) is None
    assert jobs.facts(party.db, a.id) == jobs.facts(party.db, b.id) == {}
    kept = jobs.get(party.db, a.id)
    assert kept is not None and kept.data == {} and kept.versions == {}
    assert jobs.purge_deleted(party.db) == 0  # nothing left to do: no write
    # deleted photos are never claimed nor counted
    assert jobs.claim(party.db) is None
    assert jobs.counts(party.db)["total"] == 0
    c = party.photo()
    jobs.claim(party.db)
    jobs.purge_deleted(party.db)
    assert jobs.get(party.db, a.id) is None
    assert jobs.get(party.db, c.id).rev > kept.rev


def test_analyzer_toggles(party):
    settings = party.repos.app_settings
    assert jobs.disabled_analyzers(settings) == {"age"}  # FairFace off by default
    jobs.save_disabled(settings, set(), by="admin:1")
    assert jobs.disabled_analyzers(settings) == set()
    jobs.save_disabled(settings, {"gestures", "basic", "nope"}, by="admin:1")
    assert settings.get(jobs.ANALYZERS_KEY)["disabled"] == ["gestures", "nope"]
    # basic always runs, unknown names are ignored
    assert jobs.disabled_analyzers(settings) == {"gestures"}
