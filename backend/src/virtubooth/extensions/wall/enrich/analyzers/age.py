"""`age` „Alter (FairFace)“, opt-in: a ViT trained for age (9 bins, 0-2 … 70+)
on the 4 largest face crops. Only the spread is stored, never an age per face.

Fact: `age_spread` (years between the youngest and oldest guess; 0 with fewer
than 2 faces). Off by default (RAM, ~0.5 s per face on a Pi 5).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..pipeline import Frame, Result
from . import AGE
from ._ml import Array, faces_of, onnx_session

# the middle of each FairFace bin: 0-2, 3-9, 10-19, 20-29, …, 60-69, 70+
MIDPOINTS = (1, 6, 15, 25, 35, 45, 55, 65, 75)
MAX_FACES = 4


def preprocess(crops: list[Array]) -> Array:
    batch = [
        (cv2.resize(c, (224, 224), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0 - 0.5)
        / 0.5
        for c in crops
    ]
    out: Array = np.stack(batch).transpose(0, 3, 1, 2).astype(np.float32)
    return out


class AgeAnalyzer:
    info = AGE

    def __init__(self) -> None:
        self._session: Any = None

    def load(self, models: Mapping[str, Path]) -> None:
        self._session = onnx_session(models["fairface_age"])

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        faces = faces_of(prior)[:MAX_FACES]
        if len(faces) < 2:
            return Result(facts={"age_spread": 0.0})
        logits = self._session.run(None, {"pixel_values": preprocess([f.crop for f in faces])})[0]
        ages = [MIDPOINTS[int(i)] for i in np.asarray(logits).argmax(axis=1)]
        spread = float(max(ages) - min(ages))
        return Result(facts={"age_spread": spread},
                      details=[("Altersspanne", f"etwa {spread:.0f} Jahre (Schätzung)")])  # fmt: skip


def create() -> AgeAnalyzer:
    return AgeAnalyzer()
