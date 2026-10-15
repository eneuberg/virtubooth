"""„Modelle herunterladen“: the admin's background download of the registry's
models (local file URLs here, no network): progress, idempotence, checksum,
disk space, an unwritable folder."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from virtubooth.extensions.wall.enrich import downloads, models
from virtubooth.extensions.wall.enrich.models import ModelFile


def toy(tmp_path: Path, name: str, content: bytes, *, sha: str | None = None) -> ModelFile:
    src = tmp_path / "src" / f"{name}.onnx"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(content)
    return ModelFile(name, f"{name}.onnx", src.as_uri(),
                     sha or hashlib.sha256(content).hexdigest(), len(content), "MIT")  # fmt: skip


def test_downloads_with_progress_and_verifies(tmp_path):
    a = toy(tmp_path, "a", b"a" * (3 * models.CHUNK + 5))
    b = toy(tmp_path, "b", b"b" * 10)
    dl = downloads.Downloader(tmp_path / "models")
    assert dl.progress().state == "idle"
    assert dl.start([a, b], wait=True) is True
    p = dl.progress()
    assert p.state == "done" and p.error is None and p.finished_at
    assert p.models == ("a", "b") and p.done_bytes == p.total_bytes == a.size + b.size
    assert sorted(f.name for f in (tmp_path / "models").iterdir()) == ["a.onnx", "b.onnx"]
    # a second run finds them (hash checked), downloads nothing
    (tmp_path / "src" / "a.onnx").unlink()
    assert dl.start([a], wait=True) is True and dl.progress().state == "done"


def test_nothing_to_do_and_one_at_a_time(tmp_path, monkeypatch):
    a = toy(tmp_path, "a", b"a" * 100)
    dl = downloads.Downloader(tmp_path / "models")
    assert dl.start([]) is False and dl.progress().state == "idle"
    gate = threading.Event()
    real = models.download

    def slow(*args, **kwargs):
        gate.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(models, "download", slow)
    assert dl.start([a]) is True
    assert dl.progress().state == "running"
    for _ in range(500):
        if dl.progress().current == "a":
            break
        threading.Event().wait(0.01)
    assert dl.progress().current == "a"
    assert dl.start([a]) is False  # already running: nothing changes
    gate.set()
    dl.join(5)
    assert dl.progress().state == "done"


def test_a_wrong_checksum_fails_in_german_and_leaves_nothing(tmp_path):
    bad = toy(tmp_path, "a", b"a" * 100, sha="0" * 64)
    dl = downloads.Downloader(tmp_path / "models")
    dl.start([bad], wait=True)
    p = dl.progress()
    assert p.state == "failed" and p.current is None
    assert p.error is not None and "Herunterladen fehlgeschlagen" in p.error
    assert "SHA256" in p.error and "huggingface.co" in p.error
    assert list((tmp_path / "models").iterdir()) == []
    # a retry after a failure starts again
    good = toy(tmp_path, "a", b"a" * 100)
    assert dl.start([good], wait=True) is True and dl.progress().state == "done"


def test_not_enough_disk(tmp_path, monkeypatch):
    a = toy(tmp_path, "a", b"a" * 100)
    monkeypatch.setattr(downloads, "_free_bytes", lambda _p: 50 * 1024 * 1024)
    dl = downloads.Downloader(tmp_path / "models")
    dl.start([a], min_free_bytes=2048 * 1024 * 1024, wait=True)
    p = dl.progress()
    assert p.state == "failed" and p.error is not None and "Zu wenig freier Speicher" in p.error
    assert not (tmp_path / "models").exists()


@pytest.mark.skipif(not hasattr(__import__("os"), "geteuid") or __import__("os").geteuid() == 0,
                    reason="root can write anywhere")  # fmt: skip
def test_an_unwritable_folder(tmp_path):
    a = toy(tmp_path, "a", b"a" * 100)
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        dl = downloads.Downloader(ro / "models")
        dl.start([a], wait=True)
        p = dl.progress()
        assert p.state == "failed" and p.error is not None and "nicht beschreibbar" in p.error
    finally:
        ro.chmod(0o700)


def test_one_downloader_per_folder(tmp_path):
    assert downloads.for_dest(tmp_path / "m") is downloads.for_dest(tmp_path / "m")
    assert downloads.for_dest(tmp_path / "m") is not downloads.for_dest(tmp_path / "n")
