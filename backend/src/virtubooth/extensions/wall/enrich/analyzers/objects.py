"""`objects` „Personen und Gläser“: MediaPipe ObjectDetector, EfficientDet-Lite2
int8 (COCO). Facts: `people` = max(faces, persons ≥ 0.4), `drinks` (bottle,
wine glass, cup), `phones`."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..pipeline import Box, BoxKind, Frame, Result
from . import OBJECTS
from ._ml import mp_image, rgb_array

SCORE_MIN = 0.35
PERSON_MIN = 0.4
MAX_RESULTS = 50
DRINKS = {"bottle": "Flasche", "wine glass": "Glas", "cup": "Glas"}
WANTED = ["person", "cell phone", *DRINKS]


class ObjectsAnalyzer:
    info = OBJECTS

    def __init__(self) -> None:
        self._detector: Any = None

    def load(self, models: Mapping[str, Path]) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._detector = vision.ObjectDetector.create_from_options(
            vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(models["efficientdet_lite2"])),
                score_threshold=SCORE_MIN,
                max_results=MAX_RESULTS,
                category_allowlist=WANTED,
            )
        )

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        res = self._detector.detect(mp_image(rgb))
        persons = drinks = phones = 0
        boxes: list[Box] = []
        for det in res.detections:
            cat = det.categories[0]
            name, score = cat.category_name, float(cat.score)
            bb = det.bounding_box
            label = ""
            if name == "person" and score >= PERSON_MIN:
                persons += 1
                label = "Person"
            elif name in DRINKS:
                drinks += 1
                label = DRINKS[name]
            elif name == "cell phone":
                phones += 1
                label = "Handy"
            if label:
                kind: BoxKind = "person" if name == "person" else "object"
                boxes.append(Box.from_pixels(kind, bb.origin_x, bb.origin_y, bb.width, bb.height,
                                             (w, h), label, score))  # fmt: skip
        faces = int(prior["faces"].facts.get("faces", 0)) if "faces" in prior else 0
        people = max(faces, persons)
        facts = {"people": float(people), "drinks": float(drinks), "phones": float(phones)}
        details = [("Personen", f"{people} (Schätzung)"), ("Gläser und Flaschen", str(drinks))]
        if phones:
            details.append(("Handys", str(phones)))
        return Result(facts=facts, boxes=boxes, details=details)


def create() -> ObjectsAnalyzer:
    return ObjectsAnalyzer()
