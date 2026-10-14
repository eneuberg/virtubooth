"""The model files the ML analyzers load: where they come from, where they live.

Every model has a versioned URL (Hugging Face commit, MediaPipe `/1/` path) and
a pinned SHA256; `fetch` refuses anything else. Files are looked up in
`$VB_WALL_MODELS_DIR`, `<data>/wall/models/` and `/opt/vb-models` (baked into
the ML Docker image), in that order. `fetch` writes to the first of
`--dest`, `$VB_WALL_MODELS_DIR`, `<data>/wall/models/`.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

MODELS_ENV = "VB_WALL_MODELS_DIR"
BAKED_DIR = Path("/opt/vb-models")
CHUNK = 1 << 20

_HF = "https://huggingface.co"
_MP = "https://storage.googleapis.com/mediapipe-models"


@dataclass(frozen=True)
class ModelFile:
    name: str
    file: str
    url: str
    sha256: str
    size: int
    license: str
    optional: bool = False  # only with --with-age


REGISTRY: tuple[ModelFile, ...] = (
    ModelFile(
        "yunet", "face_detection_yunet_2023mar.onnx",
        f"{_HF}/opencv/face_detection_yunet/resolve/3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232_589, "MIT",
    ),
    ModelFile(
        "face_landmarker", "face_landmarker.task",
        f"{_MP}/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff", 3_758_596, "Apache-2.0",
    ),
    ModelFile(
        "ferplus", "emotion-ferplus-8.onnx",
        f"{_HF}/onnxmodelzoo/emotion-ferplus-8/resolve/4d016bfebdb4122b1f37511c5a9d40b5c87054a8/emotion-ferplus-8.onnx",
        "a2a2ba6a335a3b29c21acb6272f962bd3d47f84952aaffa03b60986e04efa61c", 35_040_571, "MIT",
    ),
    ModelFile(
        "gesture_recognizer", "gesture_recognizer.task",
        f"{_MP}/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
        "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482", 8_373_440, "Apache-2.0",
    ),
    ModelFile(
        "efficientdet_lite2", "efficientdet_lite2.tflite",
        f"{_MP}/object_detector/efficientdet_lite2/int8/1/efficientdet_lite2.tflite",
        "b3f50554cb0ea559e90328845f7d9ba4d13c8bff372914d24e06bc8bb72fa896", 7_515_971, "Apache-2.0",
    ),
    ModelFile(
        "clip_vision", "clip_vision_model_int8.onnx",
        f"{_HF}/Xenova/clip-vit-base-patch32/resolve/d15189d7028b43f1d3e65039190477f6af591c2a/onnx/vision_model_int8.onnx",
        "0ab0c1b3ace708e539633af1744d5a95247fe4e14d3e08ff197ef82a6cb9bd93", 88_648_877, "MIT",
    ),
    ModelFile(
        "fairface_age", "fairface_age_model_int8.onnx",
        f"{_HF}/onnx-community/fairface_age_image_detection-ONNX/resolve/fd04cddf04982f6acc1ac76fb1a31b44c9285596/onnx/model_int8.onnx",
        "c6a6c231140e2111267d9ade2017543c86ff4e685795be4006f1e94e0534c8c0", 87_339_068,
        "Apache-2.0 (FairFace data CC BY 4.0)", optional=True,
    ),
)  # fmt: skip
BY_NAME = {m.name: m for m in REGISTRY}


class FetchError(Exception):
    pass


def search_dirs(data_dir: Path | None) -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get(MODELS_ENV, "").strip()
    if env:
        dirs.append(Path(env).expanduser())
    if data_dir is not None:
        dirs.append(data_dir / "wall" / "models")
    dirs.append(BAKED_DIR)
    return dirs


def default_dest(data_dir: Path) -> Path:
    env = os.environ.get(MODELS_ENV, "").strip()
    return Path(env).expanduser() if env else data_dir / "wall" / "models"


def find(name: str, dirs: Iterable[Path]) -> Path | None:
    """The model's file in the first folder that has it (size must match:
    a cheap check; `fetch` verified the hash when it wrote it)."""
    model = BY_NAME.get(name)
    if model is None:
        return None
    for folder in dirs:
        path = folder / model.file
        try:
            if path.is_file() and path.stat().st_size == model.size:
                return path
        except OSError:
            continue
    return None


def resolver(data_dir: Path | None) -> Callable[[str], Path | None]:
    dirs = search_dirs(data_dir)
    return lambda name: find(name, dirs)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(model: ModelFile, dest: Path, *, log: Callable[[str], None] = print) -> Path:
    """Download, verify the SHA256 while streaming, then rename into place
    (atomic: a broken download never leaves a file under the final name)."""
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / model.file
    part = dest / f".{model.file}.part"
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(model.url, headers={"User-Agent": "virtubooth"})
        with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:
            while chunk := resp.read(CHUNK):
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest() != model.sha256:
            raise FetchError(
                f"{model.name}: SHA256 mismatch (got {h.hexdigest()}, want {model.sha256})"
            )
        os.replace(part, final)
    except OSError as exc:
        raise FetchError(f"{model.name}: download failed: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)
    log(f"{model.name}: {final} ({model.size / 1e6:.1f} MB)")
    return final


def wanted(with_age: bool) -> list[ModelFile]:
    return [m for m in REGISTRY if with_age or not m.optional]


def fetch(
    dest: Path, *, with_age: bool = False, models: Sequence[ModelFile] | None = None,
    log: Callable[[str], None] = print,
) -> list[Path]:  # fmt: skip
    """Make sure every model is in `dest` with the right hash."""
    out: list[Path] = []
    for model in models if models is not None else wanted(with_age):
        path = dest / model.file
        if path.is_file() and sha256_of(path) == model.sha256:
            log(f"{model.name}: present")
            out.append(path)
            continue
        out.append(download(model, dest, log=log))
    return out


def missing(names: Iterable[str], data_dir: Path | None) -> list[str]:
    resolve = resolver(data_dir)
    return [n for n in names if resolve(n) is None]
