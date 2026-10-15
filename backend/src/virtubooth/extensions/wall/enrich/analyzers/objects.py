"""`objects` „Objekte“: MediaPipe ObjectDetector, EfficientDet-Lite2 int8, all
80 COCO classes.

Every detection with score ≥ `score_min` (admin setting), at most
`max_objects`, best first, becomes an entry of the photo's object list
(`photo_objects`, source `local`; stored by the worker in the same
transaction as the facts). Facts: `people` = max(faces, persons ≥ 0.4),
`drinks` (bottle, wine glass, cup), `phones`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..objects import DetectedObject
from ..pipeline import Frame, Result
from . import OBJECTS, settings_defaults

MODEL = "efficientdet_lite2"
# the detector's own floor; the admin's `score_min` filters above it
DETECT_MIN = 0.1
DETECT_MAX = 100
PERSON_MIN = 0.4
DRINKS = frozenset({"bottle", "wine glass", "cup"})
PHONES = frozenset({"cell phone"})

# German display labels of every COCO class (singular, as on the wall)
LABEL_DE: dict[str, str] = {
    "person": "Person", "bicycle": "Fahrrad", "car": "Auto", "motorcycle": "Motorrad",
    "airplane": "Flugzeug", "bus": "Bus", "train": "Zug", "truck": "Lastwagen", "boat": "Boot",
    "traffic light": "Ampel", "fire hydrant": "Hydrant", "stop sign": "Stoppschild",
    "parking meter": "Parkuhr", "bench": "Bank", "bird": "Vogel", "cat": "Katze", "dog": "Hund",
    "horse": "Pferd", "sheep": "Schaf", "cow": "Kuh", "elephant": "Elefant", "bear": "Bär",
    "zebra": "Zebra", "giraffe": "Giraffe", "backpack": "Rucksack", "umbrella": "Regenschirm",
    "handbag": "Handtasche", "tie": "Krawatte", "suitcase": "Koffer", "frisbee": "Frisbee",
    "skis": "Ski", "snowboard": "Snowboard", "sports ball": "Ball", "kite": "Drachen",
    "baseball bat": "Baseballschläger", "baseball glove": "Baseballhandschuh",
    "skateboard": "Skateboard", "surfboard": "Surfbrett", "tennis racket": "Tennisschläger",
    "bottle": "Flasche", "wine glass": "Weinglas", "cup": "Becher", "fork": "Gabel",
    "knife": "Messer", "spoon": "Löffel", "bowl": "Schüssel", "banana": "Banane",
    "apple": "Apfel", "sandwich": "Sandwich", "orange": "Orange", "broccoli": "Brokkoli",
    "carrot": "Karotte", "hot dog": "Hotdog", "pizza": "Pizza", "donut": "Donut",
    "cake": "Kuchen", "chair": "Stuhl", "couch": "Sofa", "potted plant": "Topfpflanze",
    "bed": "Bett", "dining table": "Tisch", "toilet": "Toilette", "tv": "Fernseher",
    "laptop": "Laptop", "mouse": "Maus", "remote": "Fernbedienung", "keyboard": "Tastatur",
    "cell phone": "Handy", "microwave": "Mikrowelle", "oven": "Backofen", "toaster": "Toaster",
    "sink": "Spüle", "refrigerator": "Kühlschrank", "book": "Buch", "clock": "Uhr",
    "vase": "Vase", "scissors": "Schere", "teddy bear": "Teddybär", "hair drier": "Föhn",
    "toothbrush": "Zahnbürste",
}  # fmt: skip


def label_de(label: str) -> str:
    return LABEL_DE.get(label, label)


def facts_of(objects: list[DetectedObject], faces: int) -> dict[str, float]:
    persons = sum(1 for o in objects if o.label == "person" and o.score >= PERSON_MIN)
    return {
        "people": float(max(faces, persons)),
        "drinks": float(sum(1 for o in objects if o.label in DRINKS)),
        "phones": float(sum(1 for o in objects if o.label in PHONES)),
    }


def select(
    found: list[DetectedObject], settings: Mapping[str, float] | None
) -> list[DetectedObject]:
    """The admin's filter: score ≥ score_min, best first, at most max_objects."""
    conf = settings_defaults("objects") | dict(settings or {})
    kept = [o for o in found if o.score >= conf["score_min"]]
    kept.sort(key=lambda o: -o.score)
    return kept[: int(conf["max_objects"])]


class ObjectsAnalyzer:
    info = OBJECTS

    def __init__(self) -> None:
        self._detector: Any = None

    @property
    def model_id(self) -> str:
        """`photo_objects.model` of what this analyzer finds."""
        return f"{MODEL}@{self.info.version}"

    def load(self, models: Mapping[str, Path]) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._detector = vision.ObjectDetector.create_from_options(
            vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(models[MODEL])),
                score_threshold=DETECT_MIN,
                max_results=DETECT_MAX,
            )
        )

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        # the ml extra (cv2, numpy) only here: the labels and helpers above are
        # importable without it (tests, the values catalogue)
        from ._ml import mp_image, rgb_array

        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        res = self._detector.detect(mp_image(rgb))
        found: list[DetectedObject] = []
        for det in res.detections:
            cat = det.categories[0]
            name = str(cat.category_name or "").strip().lower()
            if not name or name == "???":
                continue
            bb = det.bounding_box
            x0, y0 = max(0.0, bb.origin_x / w), max(0.0, bb.origin_y / h)
            x1 = min(1.0, (bb.origin_x + bb.width) / w)
            y1 = min(1.0, (bb.origin_y + bb.height) / h)
            box = (round(x0, 4), round(y0, 4), round(max(0.0, x1 - x0), 4),
                   round(max(0.0, y1 - y0), 4))  # fmt: skip
            found.append(DetectedObject(name, label_de(name), round(float(cat.score), 4), box))
        objects = select(found, frame.settings.get("objects"))
        faces = int(prior["faces"].facts.get("faces", 0)) if "faces" in prior else 0
        facts = facts_of(objects, faces)
        details = [
            ("Personen", f"{facts['people']:.0f} (Schätzung)"),
            ("Gläser und Flaschen", f"{facts['drinks']:.0f}"),
            ("Objekte", str(len(objects))),
        ]
        if facts["phones"]:
            details.append(("Handys", f"{facts['phones']:.0f}"))
        return Result(facts=facts, details=details, objects=objects)


def create() -> ObjectsAnalyzer:
    return ObjectsAnalyzer()
