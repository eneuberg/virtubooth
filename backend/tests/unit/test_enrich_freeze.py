"""Frozen analyses (PLAN-NIGHT N3): no rerun routes, no requeue when an analyzer
version changes or an analyzer is switched on, and no job function left that
re-queues a finished photo."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from virtubooth.core.clock import now_iso
from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.pipeline import AnalyzerInfo, Frame, Result
from virtubooth.extensions.wall.enrich.worker import Worker
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

from ..conftest import ORIGIN


class Fake:
    def __init__(self, name: str, version: str = "1") -> None:
        self.info = AnalyzerInfo(name=name, title=name, version=version, kind="basic",
                                 facts=(name,))  # fmt: skip
        self.runs = 0

    def load(self, models: object) -> None:
        pass

    def run(self, frame: Frame, prior: object) -> Result:
        self.runs += 1
        return Result(facts={self.info.name: float(self.info.version)})


@pytest.fixture
def extensions(demo_extension):
    return [demo_extension, make_extension()]


def test_no_rerun_routes(admin):
    r = admin.post("/api/x/wall/admin/analysis/rerun", json={"scope": "all"}, headers=ORIGIN)
    assert r.status_code in (404, 405)
    r = admin.post("/api/x/wall/admin/photos/abc/analysis", headers=ORIGIN)
    assert r.status_code in (404, 405)
    for name in ("rerun", "request", "stale", "requeue"):
        assert not hasattr(jobs, name), name
    assert not hasattr(Worker, "sweep")


def test_a_version_bump_or_a_new_analyzer_does_not_requeue(tmp_path: Path):
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    repos = Repositories.create(db, data)
    user = create_user(db, repos, consent_version="1", instagram=None, fp_hash=None,
                       fp_components={}, ip="10.0.0.1", user_agent="pytest")  # fmt: skip
    (data / "booth").mkdir()
    Image.new("RGB", (64, 48), (10, 200, 30)).save(data / "booth" / "p.jpg")
    public_id = new_public_id()
    repos.photos.insert(public_id=public_id, extension="booth", user_id=user.id,
                        filename="p.jpg", thumb_filename="p.jpg", width=64, height=48, size=1,
                        meta={}, created_at=now_iso())  # fmt: skip
    pid = repos.photos.internal_id(public_id)
    try:
        Worker(data, analyzers=[Fake("basic"), Fake("faces")]).run(once=True)
        row = jobs.get(db, pid)
        assert row.state == "done" and row.versions == {"basic": "1", "faces": "1"}
        # new code: a new version, and an analyzer that was not there before
        bumped, extra = Fake("faces", "2"), Fake("tags")
        worker = Worker(data, analyzers=[Fake("basic"), bumped, extra])
        assert worker.run(once=True) == 0
        assert worker.processed == 0 and bumped.runs == extra.runs == 0
        assert jobs.get(db, pid).versions == {"basic": "1", "faces": "1"}
        assert jobs.facts(db, pid) == {"basic": 1.0, "faces": 1.0, "people": 1.0}
        assert jobs.get(db, pid).attempts == 1
    finally:
        db.close()
