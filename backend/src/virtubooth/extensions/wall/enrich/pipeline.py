"""The analysis pipeline: analyzer plugins, their order, and one photo's run.

An analyzer looks at a `Frame` (the photo, RGB, long side ≤ 1280 px) plus the
results of the analyzers before it and returns a `Result`: numeric facts (the
wall's categories query them), boxes and German detail lines (admin only), and
`scratch` (face crops, landmarks, CLIP vectors) that only its dependents read.
Scratch lives in this process's memory for one photo and is never stored.

Order is topological by `needs`, ties in registry order. An analyzer that is
disabled, cannot load (no `ml` extra, missing model, load error) or whose
dependency did not run is skipped, and so are its dependents. An exception in
`run` fails the whole photo (`AnalyzerFailed`; the job retries it while
attempts < jobs.MAX_ATTEMPTS).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from PIL import Image

if TYPE_CHECKING:
    from .objects import DetectedObject

log = logging.getLogger("virtubooth.wall.enrich")

# the frame analyzers see: long side at most this many pixels
FRAME_SIDE = 1280

BoxKind = Literal["face", "hand", "person", "object"]
AnalyzerKind = Literal["basic", "ml"]


@dataclass(frozen=True)
class AnalyzerInfo:
    name: str
    title: str  # German, shown in the admin
    version: str  # bump when the facts change meaning
    kind: AnalyzerKind
    needs: tuple[str, ...] = ()  # analyzers that must run first (their results are in `prior`)
    models: tuple[str, ...] = ()  # model names (models.py registry)
    facts: tuple[str, ...] = ()  # fact keys it writes
    default_enabled: bool = True
    description: str = ""  # German, one sentence for the admin („ML-Pipeline“)


@dataclass(frozen=True)
class Box:
    """A region in the photo; coordinates 0..1, top-left origin."""

    kind: BoxKind
    x: float
    y: float
    w: float
    h: float
    label: str  # German, e.g. "fröhlich 82 %"
    score: float

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "w": round(self.w, 4),
            "h": round(self.h, 4),
            "label": self.label,
            "score": round(self.score, 3),
        }

    @classmethod
    def from_pixels(
        cls, kind: BoxKind, x: float, y: float, w: float, h: float, size: tuple[int, int],
        label: str, score: float,
    ) -> Box:  # fmt: skip
        """From pixel coordinates in an image of `size` (width, height), clipped to it."""
        fw, fh = size
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(fw), x + w), min(float(fh), y + h)
        return cls(
            kind=kind, x=x0 / fw, y=y0 / fh, w=max(0.0, x1 - x0) / fw, h=max(0.0, y1 - y0) / fh,
            label=label, score=float(score),
        )  # fmt: skip


@dataclass
class Result:
    facts: dict[str, float] = field(default_factory=dict)
    boxes: list[Box] = field(default_factory=list)
    details: list[tuple[str, str]] = field(default_factory=list)
    # the detector's objects (stored in `photo_objects`, not in the boxes)
    objects: list[DetectedObject] = field(default_factory=list)
    # in-memory only, for dependents (face boxes and crops, blendshapes, ...)
    scratch: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceLabels:
    """How the admin names a photo's source and its meta (from the extension,
    which the worker does not import: `jobs.source_labels`)."""

    title: str
    labels: Mapping[str, str] = field(default_factory=dict)  # meta key → name
    values: Mapping[str, Mapping[str, str]] = field(default_factory=dict)  # key → value → name


@dataclass(frozen=True)
class PhotoInfo:
    """The photo row as the worker claimed it."""

    id: int
    public_id: str
    extension: str
    filename: str
    created_at: str
    width: int
    height: int
    meta: Mapping[str, Any]
    user_name: str
    # the QR code the guest joined through („Otter 3“), None: unknown
    code_name: str | None = None
    # the guest switched the automatic analysis off: basic image values only
    opt_out: bool = False
    # the source's names for the details; None: the raw ids
    source: SourceLabels | None = None
    # which image `filename` is: original | filtered | photo (jobs.pick_image)
    image: str | None = None


@dataclass
class Frame:
    image: Image.Image  # RGB, long side ≤ FRAME_SIDE
    width: int  # the stored photo's size
    height: int
    photo: PhotoInfo
    # derived data several analyzers share (e.g. the numpy array); per photo
    cache: dict[str, Any] = field(default_factory=dict)
    # the admin's analyzer settings: analyzer → {key: value} (`jobs.analyzer_settings`)
    settings: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    @property
    def size(self) -> tuple[int, int]:
        """The frame's own size (width, height)."""
        return self.image.size


class Analyzer(Protocol):
    @property
    def info(self) -> AnalyzerInfo: ...

    def load(self, models: Mapping[str, Path]) -> None:
        """Load the models (name → file). Called once per process, before the first run."""

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result: ...


class AnalyzerFailed(Exception):
    """`run` of this analyzer raised (the cause is chained): the photo fails."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass
class Outcome:
    facts: dict[str, float]
    boxes: list[Box]
    details: list[tuple[str, str]]
    versions: dict[str, str]
    timings_ms: dict[str, float]
    skipped: dict[str, str]  # analyzer → why
    objects: list[DetectedObject] = field(default_factory=list)
    # analyzers that produced `objects` (the detector), for `photo_objects.model`
    object_sources: list[str] = field(default_factory=list)

    def durations_ms(self) -> dict[str, int]:
        return {k: round(v) for k, v in self.timings_ms.items()}

    def data(self) -> dict[str, Any]:
        """What `wall_analysis.data` stores (admin only)."""
        return {
            "boxes": [b.as_json() for b in self.boxes],
            "details": [{"label": k, "value": v} for k, v in self.details],
            "durations_ms": self.durations_ms(),
        }


def topological(infos: Sequence[AnalyzerInfo]) -> list[str]:
    """Names in dependency order; ties keep the given order. Unknown needs are
    allowed (that analyzer is then always skipped); a cycle is a bug."""
    names = [i.name for i in infos]
    known = set(names)
    pending = {i.name: {n for n in i.needs if n in known} for i in infos}
    order: list[str] = []
    while pending:
        ready = [n for n in names if n in pending and not pending[n]]
        if not ready:
            raise ValueError(f"analyzer dependency cycle: {sorted(pending)}")
        first = ready[0]
        order.append(first)
        del pending[first]
        for deps in pending.values():
            deps.discard(first)
    return order


# (analyzer) -> None if it can run, else a short reason (static checks: ml extra, model files)
Gate = Callable[[AnalyzerInfo], str | None]
# model name -> file, or None when missing
Resolve = Callable[[str], Path | None]


class Pipeline:
    def __init__(self, analyzers: Sequence[Analyzer], *, gate: Gate, resolve: Resolve) -> None:
        self._by_name = {a.info.name: a for a in analyzers}
        self.order = topological([a.info for a in analyzers])
        self._gate = gate
        self._resolve = resolve
        self._loaded: set[str] = set()
        # analyzer → why it could not load (kept for the process' lifetime)
        self.load_errors: dict[str, str] = {}

    def analyzers(self) -> list[Analyzer]:
        return [self._by_name[n] for n in self.order]

    def _ready(self, analyzer: Analyzer) -> str | None:
        """None when it can run (loading it on first use), else why not."""
        info = analyzer.info
        if info.name in self.load_errors:
            return self.load_errors[info.name]
        if info.name in self._loaded:
            return None
        reason = self._gate(info)
        if reason:
            return reason
        paths: dict[str, Path] = {}
        for model in info.models:
            path = self._resolve(model)
            if path is None:
                return f"Modell {model} fehlt"
            paths[model] = path
        try:
            analyzer.load(paths)
        except Exception as exc:
            log.exception("analyzer %s failed to load", info.name)
            self.load_errors[info.name] = f"Laden fehlgeschlagen: {type(exc).__name__}"
            return self.load_errors[info.name]
        self._loaded.add(info.name)
        return None

    def run(self, frame: Frame, disabled: Collection[str] = ()) -> Outcome:
        results: dict[str, Result] = {}
        skipped: dict[str, str] = {}
        timings: dict[str, float] = {}
        for name in self.order:
            analyzer = self._by_name[name]
            if name in disabled:
                skipped[name] = "ausgeschaltet"
                continue
            missing = [n for n in analyzer.info.needs if n not in results]
            if missing:
                skipped[name] = f"braucht {missing[0]}"
                continue
            reason = self._ready(analyzer)
            if reason:
                skipped[name] = reason
                continue
            started = time.perf_counter()
            try:
                results[name] = analyzer.run(frame, results)
            except Exception as exc:
                raise AnalyzerFailed(name) from exc
            timings[name] = (time.perf_counter() - started) * 1000
        return merge(results, [n for n in self.order if n in results], skipped, timings,
                     {n: self._by_name[n].info.version for n in results})  # fmt: skip


def merge(
    results: Mapping[str, Result],
    order: Sequence[str],
    skipped: dict[str, str],
    timings: dict[str, float],
    versions: dict[str, str],
) -> Outcome:
    """One outcome from all results (scratch is dropped here). Boxes of the same
    kind and place (a face that `faces` found and `emotion` labelled) become one
    box with both labels."""
    facts: dict[str, float] = {}
    boxes: dict[tuple[str, float, float, float, float], Box] = {}
    details: list[tuple[str, str]] = []
    objects: list[DetectedObject] = []
    object_sources: list[str] = []
    for name in order:
        res = results[name]
        facts.update({k: float(v) for k, v in res.facts.items()})
        details.extend(res.details)
        if res.objects:
            objects.extend(res.objects)
            object_sources.append(name)
        for box in res.boxes:
            key = (box.kind, round(box.x, 3), round(box.y, 3), round(box.w, 3), round(box.h, 3))
            old = boxes.get(key)
            if old is None:
                boxes[key] = box
            elif box.label and box.label not in old.label:
                boxes[key] = Box(old.kind, old.x, old.y, old.w, old.h,
                                 f"{old.label} · {box.label}", old.score)  # fmt: skip
    # people without the object detector: at least the faces
    if "people" not in facts and "faces" in facts:
        facts["people"] = facts["faces"]
    return Outcome(
        facts=facts, boxes=list(boxes.values()), details=details, versions=versions,
        timings_ms=timings, skipped=skipped, objects=objects, object_sources=object_sources,
    )  # fmt: skip
