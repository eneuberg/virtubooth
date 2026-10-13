"""`faces` „Gesichter“: YuNet finds the faces, MediaPipe's FaceLandmarker reads
52 blendshapes on an enlarged crop of each (smile, eyes closed, jaw open).

Facts: `faces`, `smiles`, `eyes_closed`, `mouth_open`, `face_area_max` (the
largest face box as a share of the frame, 0..1). Scratch for dependents: the
faces with their crops (largest first). No recognition, nothing stored but
counts and boxes.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2

from ..pipeline import Box, Frame, Result
from . import FACES
from ._ml import FaceCrop, crop, mp_image, rgb_array

DETECT_SIDE = 960  # YuNet input (long side); groups need more than 640
SCORE_MIN = 0.7
NMS = 0.3
TOP_K = 50
# blendshapes per photo (20-40 ms each on a Pi 5): the largest faces
MAX_LANDMARK_FACES = 8
CROP_SCALE = 1.6
SMILE = 0.5
BLINK = 0.5
JAW_OPEN = 0.5


def _blend_flags(blend: Mapping[str, float]) -> tuple[bool, bool, bool]:
    smile = (blend.get("mouthSmileLeft", 0) + blend.get("mouthSmileRight", 0)) / 2 > SMILE
    eyes = blend.get("eyeBlinkLeft", 0) > BLINK and blend.get("eyeBlinkRight", 0) > BLINK
    mouth = blend.get("jawOpen", 0) > JAW_OPEN
    return smile, eyes, mouth


class FacesAnalyzer:
    info = FACES

    def __init__(self) -> None:
        self._yunet: Any = None
        self._landmarker: Any = None

    def load(self, models: Mapping[str, Path]) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._yunet = cv2.FaceDetectorYN.create(
            str(models["yunet"]), "", (320, 320), SCORE_MIN, NMS, TOP_K
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(models["face_landmarker"])),
                output_face_blendshapes=True,
                num_faces=1,
                min_face_detection_confidence=0.3,
                min_face_presence_confidence=0.3,
            )
        )

    def detect(self, rgb: Any) -> list[tuple[float, float, float, float, float]]:
        """(x, y, w, h, score) in `rgb` pixels, largest first."""
        h, w = rgb.shape[:2]
        s = min(1.0, DETECT_SIDE / max(h, w))
        small = rgb if s >= 1.0 else cv2.resize(
            rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA
        )  # fmt: skip
        self._yunet.setInputSize((small.shape[1], small.shape[0]))
        _, dets = self._yunet.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
        if dets is None:
            return []
        found = [(float(d[0]) / s, float(d[1]) / s, float(d[2]) / s, float(d[3]) / s,
                  float(d[14])) for d in dets]  # fmt: skip
        return sorted(found, key=lambda f: f[2] * f[3], reverse=True)

    def blendshapes(self, face_crop: Any) -> dict[str, float] | None:
        res = self._landmarker.detect(mp_image(face_crop))
        if not res.face_blendshapes:
            return None
        return {c.category_name: float(c.score) for c in res.face_blendshapes[0]}

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        faces: list[FaceCrop] = []
        boxes: list[Box] = []
        smiles = eyes_closed = mouth_open = 0
        for i, (x, y, fw, fh, score) in enumerate(self.detect(rgb)):
            face = FaceCrop(
                box=(x, y, fw, fh), score=score,
                crop=crop(rgb, (x, y, fw, fh), CROP_SCALE, square=True),
                tight=crop(rgb, (x, y, fw, fh), 1.1, square=True),
            )  # fmt: skip
            notes: list[str] = []
            if i < MAX_LANDMARK_FACES:
                face.blend = self.blendshapes(face.crop)
                if face.blend:
                    smile, eyes, mouth = _blend_flags(face.blend)
                    smiles += smile
                    eyes_closed += eyes
                    mouth_open += mouth
                    notes += [n for n, on in (("lächelt", smile), ("Augen zu", eyes),
                                              ("Mund offen", mouth)) if on]  # fmt: skip
            faces.append(face)
            label = "Gesicht" + (f" ({', '.join(notes)})" if notes else "")
            boxes.append(Box.from_pixels("face", x, y, fw, fh, (w, h), label, score))
        area = max((f.box[2] * f.box[3] for f in faces), default=0.0) / float(w * h)
        n = len(faces)
        facts = {
            "faces": float(n),
            "smiles": float(smiles),
            "eyes_closed": float(eyes_closed),
            "mouth_open": float(mouth_open),
            "face_area_max": round(min(1.0, area), 4),
        }
        details = [("Gesichter", f"{n} (Schätzung)")]
        if n:
            details += [
                ("Lächeln", f"{smiles} (Schätzung)"),
                ("Augen zu", f"{eyes_closed} (Schätzung)"),
                ("Mund offen", f"{mouth_open} (Schätzung)"),
            ]
        return Result(facts=facts, boxes=boxes, details=details, scratch={"faces": faces})


def create() -> FacesAnalyzer:
    return FacesAnalyzer()
