"""`emotion` „Gesichtsausdruck“: FER+ (8 classes) on each face found by `faces`.

Facts: `happy_max`, `sad_max`, `surprise_max` 0..1: the highest probability
among faces whose top-1 class it is, and only above a confidence floor (FER+
is noisy on party photos, MODELS.md §6); 0 otherwise. A fun guess, never an
assessment of a person.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..pipeline import Box, Frame, Result
from . import EMOTION
from ._ml import faces_of, onnx_session, rgb_array, softmax

CLASSES = ("neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt")
GERMAN = {
    "neutral": "neutral", "happiness": "fröhlich", "surprise": "überrascht",
    "sadness": "traurig", "anger": "grimmig", "disgust": "angewidert", "fear": "erschrocken",
    "contempt": "skeptisch",
}  # fmt: skip
FACTS = {"happiness": "happy_max", "sadness": "sad_max", "surprise": "surprise_max"}
# top-1 must reach this to count (and to label the box)
FLOOR = 0.4


class EmotionAnalyzer:
    info = EMOTION

    def __init__(self) -> None:
        self._session: Any = None
        self._input = ""

    def load(self, models: Mapping[str, Path]) -> None:
        self._session = onnx_session(models["ferplus"])
        self._input = self._session.get_inputs()[0].name

    def probabilities(self, face_rgb: Any) -> Any:
        gray = cv2.resize(cv2.cvtColor(face_rgb, cv2.COLOR_RGB2GRAY), (64, 64),
                          interpolation=cv2.INTER_AREA)  # fmt: skip
        x = gray.astype(np.float32)[None, None]  # raw 0..255, as FER+ was trained
        logits = self._session.run(None, {self._input: x})[0][0]
        return softmax(np.asarray(logits, dtype=np.float32))

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        facts = dict.fromkeys(FACTS.values(), 0.0)
        boxes: list[Box] = []
        seen: Counter[str] = Counter()
        for face in faces_of(prior):
            p = self.probabilities(face.tight)
            top = int(np.argmax(p))
            name, score = CLASSES[top], float(p[top])
            if score < FLOOR:
                continue
            seen[GERMAN[name]] += 1
            if name in FACTS:
                facts[FACTS[name]] = max(facts[FACTS[name]], round(score, 4))
            x, y, fw, fh = face.box
            boxes.append(Box.from_pixels("face", x, y, fw, fh, (w, h),
                                         f"{GERMAN[name]} {round(score * 100)} %", score))  # fmt: skip
        summary = ", ".join(f"{n}× {label}" for label, n in seen.most_common()) or "–"
        return Result(facts=facts, boxes=boxes,
                      details=[("Gesichtsausdruck", f"{summary} (Schätzung)")])  # fmt: skip


def create() -> EmotionAnalyzer:
    return EmotionAnalyzer()
