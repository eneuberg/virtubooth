"""Test images („Testbild“ in the admin's ML-Pipeline): the pipeline on an
uploaded image, without storing anything as a party photo.

The app and the worker are separate processes that share the data folder, so
a test is a pair of files in `<data>/wall/test/`:

- the app writes `<uuid>.jpg` (the image), then `<uuid>.json` `{"analyzers":
  [names] | null}` (atomically: the request exists only once complete);
- the worker looks there before it claims a photo, runs the pipeline in
  memory, writes `<uuid>.result.json` (atomically) and deletes the request;
- `submit()` polls every 100 ms for the result, reads it and cleans up.

Nothing reaches `photos` or a `wall_*` table. A request nobody answers is
removed by `submit()` on timeout, or by the worker once it is STALE_S old.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError

from .objects import DetectedObject

if TYPE_CHECKING:
    from ....runtime import Core
    from .pipeline import Outcome, PhotoInfo

log = logging.getLogger("virtubooth.wall.enrich")

POLL_S = 0.1
STALE_S = 120.0
_ID_LEN = 32


class WorkerOff(Exception):
    """No analysis worker is running (switched off, crashed, not started)."""


@dataclass
class TestRun:
    __test__ = False  # not a pytest test class

    width: int
    height: int
    facts: dict[str, float] = field(default_factory=dict)
    boxes: list[dict[str, Any]] = field(default_factory=list)
    details: list[dict[str, str]] = field(default_factory=list)
    objects: list[DetectedObject] = field(default_factory=list)
    durations_ms: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    # analyzer → why it did not run (switched off, model missing, ...)
    skipped: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "facts": self.facts,
            "boxes": self.boxes,
            "details": self.details,
            "objects": [
                {"label": o.label, "label_de": o.label_de, "score": o.score,
                 "box": list(o.box) if o.box is not None else None}  # fmt: skip
                for o in self.objects
            ],
            "durations_ms": self.durations_ms,
            "error": self.error,
            "skipped": self.skipped,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> TestRun:
        objs = []
        for o in raw.get("objects") or []:
            box = o.get("box")
            objs.append(
                DetectedObject(
                    label=str(o["label"]), label_de=str(o["label_de"]), score=float(o["score"]),
                    box=(float(box[0]), float(box[1]), float(box[2]), float(box[3]))
                    if box else None,
                )  # fmt: skip
            )
        return cls(
            width=int(raw.get("width") or 0), height=int(raw.get("height") or 0),
            facts={str(k): float(v) for k, v in (raw.get("facts") or {}).items()},
            boxes=list(raw.get("boxes") or []), details=list(raw.get("details") or []),
            objects=objs,
            durations_ms={str(k): int(v) for k, v in (raw.get("durations_ms") or {}).items()},
            error=raw.get("error"), skipped=dict(raw.get("skipped") or {}),
        )  # fmt: skip


def requests_dir(data_dir: Path) -> Path:
    return data_dir / "wall" / "test"


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _cleanup(folder: Path, rid: str) -> None:
    for name in (f"{rid}.json", f"{rid}.jpg", f"{rid}.result.json"):
        with contextlib.suppress(OSError):
            (folder / name).unlink()


# ------------------------------------------------------------- app side


def submit(
    core: Core, image: bytes, analyzers: Collection[str] | None, timeout_s: float = 30
) -> TestRun:
    """Run the worker's pipeline on `image`; raises WorkerOff (no worker
    running) or TimeoutError. `analyzers` None: every enabled analyzer; else
    these (plus what they need; `basic` always)."""
    from .service import EnrichmentService

    if EnrichmentService.of(core).worker().state != "running":
        raise WorkerOff("the analysis worker is not running")
    return submit_to(requests_dir(core.settings.data_dir), image, analyzers, timeout_s)


def submit_to(
    folder: Path, image: bytes, analyzers: Collection[str] | None, timeout_s: float = 30,
    *, alive: Callable[[], bool] | None = None,
) -> TestRun:  # fmt: skip
    """`submit` against a folder (tests, the CLI); `alive` is asked while
    waiting: False → WorkerOff."""
    folder.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    names = sorted(set(analyzers)) if analyzers is not None else None
    _write_atomic(folder / f"{rid}.jpg", image)
    _write_atomic(folder / f"{rid}.json", json.dumps({"analyzers": names}).encode())
    result = folder / f"{rid}.result.json"
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if result.is_file():
                try:
                    raw = json.loads(result.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raw = None
                if isinstance(raw, dict):
                    return TestRun.from_json(raw)
            if alive is not None and not alive():
                raise WorkerOff("the analysis worker stopped")
            if time.monotonic() >= deadline:
                raise TimeoutError("no answer from the analysis worker")
            time.sleep(POLL_S)
    finally:
        _cleanup(folder, rid)


# ---------------------------------------------------------- worker side


def pending(folder: Path) -> list[str]:
    """Request ids, oldest first (stale ones are removed on the way)."""
    if not folder.is_dir():
        return []
    out: list[tuple[float, str]] = []
    now = time.time()
    for path in folder.glob("*.json"):
        rid = path.name[: -len(".json")]
        if len(rid) != _ID_LEN or not all(ch in "0123456789abcdef" for ch in rid):
            continue  # also every `<id>.result.json`
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime > STALE_S:
            _cleanup(folder, rid)
            continue
        out.append((mtime, rid))
    return [rid for _, rid in sorted(out)]


def wanted_analyzers(requested: Collection[str] | None, enabled: Collection[str],
                     needs: Mapping[str, tuple[str, ...]]) -> set[str]:  # fmt: skip
    """What a test runs: the enabled ones, or the requested ones plus what
    they need (transitively); `basic` always."""
    if requested is None:
        return set(enabled) | {"basic"}
    out = {"basic"}
    todo = [n for n in requested if n in needs]
    while todo:
        name = todo.pop()
        if name in out:
            continue
        out.add(name)
        todo.extend(n for n in needs[name] if n in needs)
    return out


def answer(
    folder: Path, rid: str,
    run: Callable[[Image.Image, Collection[str] | None], tuple[Outcome, PhotoInfo | None]],
) -> None:  # fmt: skip
    """Work off one request: run, write the result, delete the request."""
    req, img_path = folder / f"{rid}.json", folder / f"{rid}.jpg"
    try:
        raw = json.loads(req.read_text(encoding="utf-8"))
        names = raw.get("analyzers") if isinstance(raw, dict) else None
        requested = [str(n) for n in names] if isinstance(names, list) else None
    except (OSError, ValueError):
        requested = None
    result: TestRun
    try:
        with Image.open(img_path) as img:
            img.load()
            image = img.copy()
        width, height = image.size
        outcome, _ = run(image, requested)
        result = TestRun(
            width=width, height=height, facts=dict(outcome.facts),
            boxes=[b.as_json() for b in outcome.boxes],
            details=[{"label": k, "value": v} for k, v in outcome.details],
            objects=list(outcome.objects), durations_ms=outcome.durations_ms(),
            skipped=dict(outcome.skipped),
        )  # fmt: skip
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        result = TestRun(width=0, height=0, error="Bild konnte nicht gelesen werden.")
    except Exception as exc:
        log.exception("test image %s failed", rid)
        result = TestRun(width=0, height=0, error=f"Analyse fehlgeschlagen ({type(exc).__name__})")
    try:
        _write_atomic(
            folder / f"{rid}.result.json",
            json.dumps(result.as_json(), ensure_ascii=False).encode("utf-8"),
        )
    finally:
        for path in (req, img_path):
            with contextlib.suppress(OSError):
                path.unlink()
