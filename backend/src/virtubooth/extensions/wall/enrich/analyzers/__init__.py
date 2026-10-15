"""The analyzer registry.

The infos live here, importable without the `ml` extra (the app process lists
them in the admin). Each analyzer's code is in its own module, imported only by
the worker when it builds the pipeline (`create_all`).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from collections.abc import Collection
from dataclasses import dataclass
from functools import cache

from ..pipeline import Analyzer, AnalyzerInfo

log = logging.getLogger("virtubooth.wall.enrich")

BASIC = AnalyzerInfo(
    name="basic", title="Bildwerte", version="1", kind="basic",
    facts=("brightness", "colorfulness", "sharpness"),
    description="Helligkeit, Farbigkeit und Schärfe des ganzen Bildes; läuft immer.",
)  # fmt: skip
FACES = AnalyzerInfo(
    name="faces", title="Gesichter", version="1", kind="ml",
    models=("yunet", "face_landmarker"),
    facts=("faces", "smiles", "eyes_closed", "mouth_open", "face_area_max"),
    description="Findet Gesichter und erkennt Lächeln, offene Münder und geschlossene Augen "
    "(keine Gesichtserkennung).",
)  # fmt: skip
EMOTION = AnalyzerInfo(
    name="emotion", title="Gesichtsausdruck", version="1", kind="ml", needs=("faces",),
    models=("ferplus",), facts=("happy_max", "sad_max", "surprise_max"),
    description="Schätzt pro Gesicht, wie fröhlich, traurig oder überrascht es aussieht.",
)  # fmt: skip
GESTURES = AnalyzerInfo(
    name="gestures", title="Hände und Gesten", version="1", kind="ml",
    models=("gesture_recognizer",), facts=("hands", "peace", "thumbs_up", "rock"),
    description="Zählt Hände und erkennt Peace-Zeichen, Daumen hoch und Pommesgabeln.",
)  # fmt: skip
OBJECTS = AnalyzerInfo(
    name="objects", title="Objekte", version="2", kind="ml",
    models=("efficientdet_lite2",), facts=("people", "drinks", "phones"),
    description="Erkennt Personen und Dinge im Bild (z. B. Glas, Flasche, Handy, Kuchen) "
    "und speichert sie als Objektliste mit Rahmen.",
)  # fmt: skip
TAGS = AnalyzerInfo(
    name="tags", title="Brillen, Hüte, Altersgruppe", version="1", kind="ml", needs=("faces",),
    models=("clip_vision",), facts=("glasses", "hats", "age_groups"),
    description="Erkennt Brillen und Hüte und schätzt grobe Altersgruppen pro Gesicht.",
)  # fmt: skip
AGE = AnalyzerInfo(
    name="age", title="Alter (FairFace)", version="1", kind="ml", needs=("faces",),
    models=("fairface_age",), facts=("age_spread",), default_enabled=False,
    description="Schätzt das Alter pro Gesicht für die Altersspanne eines Fotos (langsam).",
)  # fmt: skip

INFOS: tuple[AnalyzerInfo, ...] = (BASIC, FACES, EMOTION, GESTURES, OBJECTS, TAGS, AGE)
BY_NAME = {i.name: i for i in INFOS}
# analyzers that are off until the admin switches them on (settings key absent)
DEFAULT_DISABLED: tuple[str, ...] = tuple(i.name for i in INFOS if not i.default_enabled)
# never switched off: metadata and image values are cheap and need nothing
ALWAYS_ON = frozenset({"basic"})


@dataclass(frozen=True)
class SettingSpec:
    """One number the admin can set for an analyzer („ML-Pipeline“)."""

    key: str
    title: str  # German
    min: float
    max: float
    step: float
    default: float
    integer: bool = False


# analyzer → its settings (`x.wall.analyzers.settings`); they apply to photos
# analysed afterwards only (frozen analyses never change)
SETTINGS: dict[str, tuple[SettingSpec, ...]] = {
    "objects": (
        SettingSpec("score_min", "Mindest-Sicherheit", 0.1, 0.9, 0.05, 0.35),
        SettingSpec("max_objects", "Höchstens Objekte pro Foto", 1, 100, 1, 50, integer=True),
    ),
}


def settings_defaults(name: str) -> dict[str, float]:
    return {s.key: s.default for s in SETTINGS.get(name, ())}


ML_PACKAGES = ("numpy", "cv2", "onnxruntime", "mediapipe")
THREADS_ENV = "VB_WALL_THREADS"
DEFAULT_THREADS = 3


def thread_limit() -> int:
    """Threads per inference ($VB_WALL_THREADS, default 3 so the web server
    keeps a core on a Pi 5; 0 = the libraries' default, all cores)."""
    try:
        return max(0, int(os.environ.get(THREADS_ENV, "").strip() or DEFAULT_THREADS))
    except ValueError:
        return DEFAULT_THREADS


@cache
def ml_installed() -> bool:
    """The `ml` extra is installed (cheap: finds the packages, imports nothing)."""
    try:
        return all(importlib.util.find_spec(p) is not None for p in ML_PACKAGES)
    except (ImportError, ValueError):
        return False


def create(name: str) -> Analyzer:
    module = importlib.import_module(f"{__name__}.{name}")
    analyzer: Analyzer = module.create()
    return analyzer


def create_all(names: Collection[str] | None = None) -> list[Analyzer]:
    """Instances of the registered analyzers (all, or `names`), registry order.
    An ML analyzer whose module cannot even be imported is left out (logged)."""
    out: list[Analyzer] = []
    for info in INFOS:
        if names is not None and info.name not in names:
            continue
        if info.kind == "ml" and not ml_installed():
            continue
        try:
            out.append(create(info.name))
        except ImportError:
            log.exception("analyzer %s cannot be imported", info.name)
    return out
