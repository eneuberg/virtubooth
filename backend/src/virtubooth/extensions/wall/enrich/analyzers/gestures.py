"""`gestures` „Hände und Gesten“: MediaPipe GestureRecognizer (hand landmarks +
canned gestures) on the frame.

Facts: `hands`, `peace` (Victory), `thumbs_up` (Thumb_Up), `rock` (index and
pinky up, middle and ring folded, from the landmarks; ILoveYou counts too).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..pipeline import Box, Frame, Result
from . import GESTURES
from ._ml import mp_image, rgb_array

MAX_HANDS = 12
MIN_DETECTION = 0.4
GESTURE_MIN = 0.5
LABELS = {"peace": "✌️ Peace", "thumbs_up": "👍 Daumen hoch", "rock": "🤘 Rock"}
# landmark indexes: wrist, then (pip, tip) per finger
WRIST = 0
INDEX, MIDDLE, RING, PINKY = (6, 8), (10, 12), (14, 16), (18, 20)


def _extended(pts: Sequence[tuple[float, float]], finger: tuple[int, int]) -> bool:
    pip, tip = finger
    return math.dist(pts[WRIST], pts[tip]) > 1.1 * math.dist(pts[WRIST], pts[pip])


def is_rock(pts: Sequence[tuple[float, float]]) -> bool:
    """🤘: index and pinky stretched, middle and ring folded."""
    return (
        _extended(pts, INDEX) and _extended(pts, PINKY)
        and not _extended(pts, MIDDLE) and not _extended(pts, RING)
    )  # fmt: skip


class GesturesAnalyzer:
    info = GESTURES

    def __init__(self) -> None:
        self._recognizer: Any = None

    def load(self, models: Mapping[str, Path]) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._recognizer = vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=str(models["gesture_recognizer"])),
                num_hands=MAX_HANDS,
                min_hand_detection_confidence=MIN_DETECTION,
            )
        )

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        res = self._recognizer.recognize(mp_image(rgb))
        counts = {"peace": 0, "thumbs_up": 0, "rock": 0}
        boxes: list[Box] = []
        for i, landmarks in enumerate(res.hand_landmarks):
            pts = [(lm.x * w, lm.y * h) for lm in landmarks]
            gesture, score = "", 0.0
            if i < len(res.gestures) and res.gestures[i]:
                gesture, score = res.gestures[i][0].category_name, float(res.gestures[i][0].score)
            kind = ""
            if gesture == "Victory" and score >= GESTURE_MIN:
                kind = "peace"
            elif gesture == "Thumb_Up" and score >= GESTURE_MIN:
                kind = "thumbs_up"
            elif gesture == "ILoveYou" or is_rock(pts):
                kind = "rock"
            if kind:
                counts[kind] += 1
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            pad = 0.1 * max(max(xs) - min(xs), max(ys) - min(ys))
            boxes.append(Box.from_pixels(
                "hand", min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad,
                max(ys) - min(ys) + 2 * pad, (w, h), LABELS.get(kind, "Hand"),
                score if kind else 1.0,
            ))  # fmt: skip
        hands = len(res.hand_landmarks)
        facts = {"hands": float(hands), **{k: float(v) for k, v in counts.items()}}
        details = [("Hände", f"{hands} (Schätzung)")]
        gestures = [f"{v}× {LABELS[k]}" for k, v in counts.items() if v]
        if gestures:
            details.append(("Gesten", ", ".join(gestures)))
        return Result(facts=facts, boxes=boxes, details=details)


def create() -> GesturesAnalyzer:
    return GesturesAnalyzer()
