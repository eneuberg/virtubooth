"""Model downloads: SHA256-pinned, atomic, local file URLs in tests; lookup order."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from virtubooth.extensions.wall.enrich import models
from virtubooth.extensions.wall.enrich.models import FetchError, ModelFile


def source(tmp_path: Path, content: bytes = b"weights" * 1000) -> tuple[Path, str]:
    path = tmp_path / "src" / "model.onnx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def model(path: Path, sha: str, size: int) -> ModelFile:
    return ModelFile("toy", "toy.onnx", path.as_uri(), sha, size, "MIT")


def test_fetch_verifies_and_renames(tmp_path):
    src, sha = source(tmp_path)
    dest = tmp_path / "models"
    lines: list[str] = []
    (out,) = models.fetch(dest, models=[model(src, sha, src.stat().st_size)], log=lines.append)
    assert out == dest / "toy.onnx" and out.read_bytes() == src.read_bytes()
    assert sorted(p.name for p in dest.iterdir()) == ["toy.onnx"]  # no .part left
    # a present file with the right hash is not downloaded again
    src.unlink()
    models.fetch(dest, models=[model(src, sha, 7000)], log=lines.append)
    assert lines[-1] == "toy: present"


def test_a_wrong_hash_is_rejected_and_leaves_nothing(tmp_path):
    src, _ = source(tmp_path)
    dest = tmp_path / "models"
    with pytest.raises(FetchError, match="SHA256 mismatch"):
        models.fetch(dest, models=[model(src, "0" * 64, src.stat().st_size)], log=print)
    assert list(dest.iterdir()) == []


def test_a_broken_download_is_reported(tmp_path):
    with pytest.raises(FetchError, match="download failed"):
        models.download(model(tmp_path / "missing.onnx", "0" * 64, 1), tmp_path / "m", log=print)
    assert list((tmp_path / "m").iterdir()) == []


def test_lookup_order_and_size_check(tmp_path, monkeypatch):
    env_dir, data = tmp_path / "env", tmp_path / "data"
    yunet = models.BY_NAME["yunet"]
    (data / "wall" / "models").mkdir(parents=True)
    (data / "wall" / "models" / yunet.file).write_bytes(b"x" * yunet.size)
    assert models.find("yunet", models.search_dirs(data)) == data / "wall/models" / yunet.file
    monkeypatch.setenv(models.MODELS_ENV, str(env_dir))
    env_dir.mkdir()
    (env_dir / yunet.file).write_bytes(b"short")  # wrong size: ignored
    assert models.find("yunet", models.search_dirs(data)) == data / "wall/models" / yunet.file
    (env_dir / yunet.file).write_bytes(b"x" * yunet.size)
    assert models.find("yunet", models.search_dirs(data)) == env_dir / yunet.file
    assert models.default_dest(data) == env_dir
    assert models.missing(["yunet", "ferplus"], data) == ["ferplus"]


def test_registry_pins_versioned_urls():
    for m in models.REGISTRY:
        assert len(m.sha256) == 64 and m.size > 0 and m.license
        assert "/latest/" not in m.url and "/resolve/main/" not in m.url
    assert [m.name for m in models.wanted(with_age=False)] == [
        "yunet", "face_landmarker", "ferplus", "gesture_recognizer", "efficientdet_lite2",
        "clip_vision",
    ]  # fmt: skip
    assert models.wanted(with_age=True)[-1].name == "fairface_age"
