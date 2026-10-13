"""The real worker process under its supervisor: analyses a photo, is restarted
after SIGKILL, exits when its stdin closes, never spawns with VB_WALL_WORKER=off."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PIL import Image

from virtubooth.core.clock import now_iso
from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.supervisor import Supervisor, worker_command
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user


@pytest.fixture
def data_dir(tmp_path: Path) -> Iterator[tuple[Path, Database, int]]:
    """A data dir with one demo photo (ML analyzers find no models here: basic only)."""
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    repos = Repositories.create(db, data)
    user = create_user(db, repos, consent_version="1", instagram=None, fp_hash=None,
                       fp_components={}, ip="10.0.0.1", user_agent="pytest")  # fmt: skip
    (data / "demo").mkdir()
    Image.new("RGB", (160, 120), (30, 140, 200)).save(data / "demo" / "a.jpg")
    public_id = new_public_id()
    repos.photos.insert(public_id=public_id, extension="demo", user_id=user.id,
                        filename="a.jpg", thumb_filename="a.jpg", width=160, height=120, size=1,
                        meta={}, created_at=now_iso())  # fmt: skip
    yield data, db, repos.photos.internal_id(public_id) or 0
    db.close()


def wait_for(check: Callable[[], object], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError("timed out")


def state(db: Database, photo_id: int) -> str | None:
    row = jobs.get(db, photo_id)
    return row.state if row else None


def test_supervised_worker_analyses_and_is_restarted(data_dir):
    data, db, photo_id = data_dir
    sup = Supervisor(data, min_backoff=0.2)
    sup.start()
    try:
        wait_for(lambda: state(db, photo_id) == "done")
        assert jobs.facts(db, photo_id).keys() >= {"brightness", "colorfulness", "sharpness"}
        wait_for(lambda: sup.state == "running")
        first = sup.pid
        assert first is not None
        os.kill(first, signal.SIGKILL)
        wait_for(lambda: sup.pid != first and sup.state in ("starting", "running"))
        assert sup.last_exit == -signal.SIGKILL and sup.restarts == 1
        proc = sup.process
        assert proc is not None and proc.poll() is None
    finally:
        sup.stop()
    assert sup.state == "stopped" and proc.poll() is not None


def test_worker_exits_when_stdin_closes(data_dir):
    data, db, photo_id = data_dir
    proc = subprocess.Popen(worker_command(data), stdin=subprocess.PIPE)
    try:
        wait_for(lambda: state(db, photo_id) == "done")
        assert proc.poll() is None
        assert proc.stdin is not None
        proc.stdin.close()  # the app died
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_off_never_spawns(data_dir, monkeypatch):
    data, _db, _ = data_dir
    monkeypatch.setenv("VB_WALL_WORKER", "off")
    sup = Supervisor(data)
    sup.start()
    assert sup.state == "off" and sup.process is None
    sup.stop()
    assert sup.state == "off"
