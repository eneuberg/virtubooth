"""Test images through the worker (`enrich/testjobs.py`): request files in
`<data>/wall/test/`, answered in memory before photos, nothing stored;
`submit()` cleans up, times out, and refuses without a running worker."""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from PIL import Image

from virtubooth.db.database import Database
from virtubooth.extensions.wall.enrich import testjobs
from virtubooth.extensions.wall.enrich.analyzers.basic import BasicAnalyzer
from virtubooth.extensions.wall.enrich.objects import DetectedObject
from virtubooth.extensions.wall.enrich.pipeline import AnalyzerInfo, Box, Frame, Result
from virtubooth.extensions.wall.enrich.testjobs import TestRun, WorkerOff
from virtubooth.extensions.wall.enrich.worker import Worker

TABLES = ("photos", "wall_analysis", "wall_facts", "photo_objects", "photo_detection_runs")


class FakeDetector:
    info = AnalyzerInfo(name="objects", title="Objekte", version="2", kind="basic",
                        facts=("people",))  # fmt: skip

    def load(self, models: Mapping[str, Path]) -> None:
        pass

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        return Result(
            facts={"people": 1.0},
            boxes=[Box("face", 0.1, 0.1, 0.2, 0.2, "Gesicht", 0.9)],
            objects=[DetectedObject("hat", "Hut", 0.8, (0.1, 0.0, 0.3, 0.2))],
        )


def jpeg(size: tuple[int, int] = (320, 240)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 40, 90)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[Path, Worker]]:
    data = tmp_path / "data"
    Database(data / "virtubooth.db").close()
    worker = Worker(data, analyzers=[BasicAnalyzer(), FakeDetector()], idle_s=0.02,
                    watch_parent=False)  # fmt: skip
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    yield data, worker
    worker.stop.set()
    thread.join(5)


def counts(data: Path) -> dict[str, int]:
    db = Database(data / "virtubooth.db")
    try:
        return {t: int(db.one(f"SELECT COUNT(*) FROM {t}")[0]) for t in TABLES}
    finally:
        db.close()


def test_the_worker_answers_in_memory(running):
    data, worker = running
    folder = testjobs.requests_dir(data)
    run = testjobs.submit_to(folder, jpeg(), None, timeout_s=10)
    assert (run.width, run.height, run.error) == (320, 240, None)
    assert set(run.facts) >= {"brightness", "colorfulness", "sharpness", "people"}
    assert run.objects == [DetectedObject("hat", "Hut", 0.8, (0.1, 0.0, 0.3, 0.2))]
    assert run.boxes[0]["kind"] == "face" and set(run.durations_ms) == {"basic", "objects"}
    assert any(d["label"] == "Helligkeit" for d in run.details)
    # only what was asked for (plus basic)
    run = testjobs.submit_to(folder, jpeg(), ["basic"], timeout_s=10)
    assert "people" not in run.facts and run.objects == []
    assert run.skipped == {"objects": "ausgeschaltet"}
    # nothing stored, nothing left in the folder
    assert counts(data) == dict.fromkeys(TABLES, 0)
    assert list(folder.iterdir()) == []
    assert worker.tests == 2


def test_a_broken_image_is_an_error_result(running):
    data, _ = running
    run = testjobs.submit_to(testjobs.requests_dir(data), b"not a jpeg", None, timeout_s=10)
    assert run.error == "Bild konnte nicht gelesen werden."


def test_timeout_cleans_up(tmp_path: Path):
    folder = tmp_path / "test"
    with pytest.raises(TimeoutError):
        testjobs.submit_to(folder, jpeg(), None, timeout_s=0.25)
    assert list(folder.iterdir()) == []
    with pytest.raises(WorkerOff):
        testjobs.submit_to(folder, jpeg(), None, timeout_s=5, alive=lambda: False)
    assert list(folder.iterdir()) == []


def test_submit_needs_a_running_worker(core):
    with pytest.raises(WorkerOff):
        testjobs.submit(core, jpeg(), None, timeout_s=1)


def test_stale_and_foreign_files_are_ignored(tmp_path: Path):
    import os
    import time

    folder = tmp_path / "test"
    folder.mkdir()
    (folder / "notes.json").write_text("{}")
    old = folder / ("a" * 32 + ".json")
    old.write_text("{}")
    (folder / ("a" * 32 + ".jpg")).write_bytes(jpeg())
    past = time.time() - testjobs.STALE_S - 5
    os.utime(old, (past, past))
    fresh = folder / ("b" * 32 + ".json")
    fresh.write_text("{}")
    assert testjobs.pending(folder) == ["b" * 32]
    assert not old.exists() and not (folder / ("a" * 32 + ".jpg")).exists()


def test_wanted_analyzers():
    needs = {"basic": (), "faces": (), "emotion": ("faces",), "age": ("faces",)}
    assert testjobs.wanted_analyzers(["emotion"], {"basic"}, needs) == {"basic", "faces", "emotion"}
    assert testjobs.wanted_analyzers(None, {"faces", "age"}, needs) == {"basic", "faces", "age"}
    assert testjobs.wanted_analyzers(["nope"], set(), needs) == {"basic"}


def test_testrun_round_trip():
    run = TestRun(width=3, height=2, facts={"a": 1.0},
                  objects=[DetectedObject("cup", "Becher", 0.5, None)],
                  durations_ms={"a": 4}, skipped={"b": "x"})  # fmt: skip
    assert TestRun.from_json(run.as_json()) == run
