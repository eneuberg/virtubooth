"""`tags` „Brillen, Hüte, Altersgruppe“: CLIP ViT-B/32 (vision tower, int8)
zero-shot on the face crops of `faces` (the 4 largest), against text prompts
embedded once offline (`clip_prompts.npy`, made by `make_clip_prompts.py`).

Facts: `glasses` (faces with glasses or sunglasses), `hats` (hats and caps),
`age_groups` (distinct generations among the faces: kids, adults, seniors;
1–3). The image vectors live in memory for one photo only.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..pipeline import Box, Frame, Result
from . import TAGS
from ._ml import Array, faces_of, onnx_session, rgb_array, softmax

PROMPTS_FILE = Path(__file__).with_name("clip_prompts.npy")
# (group, key, prompt); the rows of clip_prompts.npy, in this order
PROMPTS: tuple[tuple[str, str, str], ...] = (
    ("glasses", "glasses", "a photo of a face with eyeglasses"),
    ("glasses", "sunglasses", "a photo of a face with sunglasses"),
    ("glasses", "none", "a photo of a face with bare eyes"),
    ("glasses", "none", "a photo of a face"),
    ("hat", "hat", "a photo of a face with a hat on the head"),
    ("hat", "cap", "a photo of a face with a cap on the head"),
    ("hat", "none", "a photo of a face with hair on the head"),
    ("hat", "none", "a photo of a bald head"),
    ("hat", "none", "a photo of a face"),
    ("age", "child", "a photo of a child's face"),
    ("age", "teen", "a photo of a teenager's face"),
    ("age", "young", "a photo of a young adult's face"),
    ("age", "middle", "a photo of a middle-aged person's face"),
    ("age", "elderly", "a photo of an elderly person's face"),
)
GENERATION = {"child": 0, "teen": 0, "young": 1, "middle": 1, "elderly": 2}
GENERATION_NAMES = ("Kinder", "Erwachsene", "Senioren")
MAX_FACES = 4
LOGIT_SCALE = 100.0
# calibrated on sample faces (NASA crew photos): bare faces stay below
GLASSES_MIN = 0.8
HAT_MIN = 0.7
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def preprocess(crops: list[Array]) -> Array:
    """CLIP input: square (crops already are), 224 px, normalised, NCHW."""
    batch = []
    for c in crops:
        img = cv2.resize(c, (224, 224), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
        batch.append(((img - MEAN) / STD).transpose(2, 0, 1))
    out: Array = np.stack(batch).astype(np.float32)
    return out


def group_probs(embeds: Array, text: Array, group: str) -> tuple[list[str], Array]:
    rows = [i for i, p in enumerate(PROMPTS) if p[0] == group]
    keys = [PROMPTS[i][1] for i in rows]
    return keys, softmax(LOGIT_SCALE * embeds @ text[rows].T)


class TagsAnalyzer:
    info = TAGS

    def __init__(self) -> None:
        self._session: Any = None
        self._text: Array | None = None

    def load(self, models: Mapping[str, Path]) -> None:
        text = np.load(PROMPTS_FILE).astype(np.float32)
        if text.shape[0] != len(PROMPTS):
            raise ValueError(f"{PROMPTS_FILE.name} has {text.shape[0]} rows, want {len(PROMPTS)}")
        self._text = text / np.linalg.norm(text, axis=1, keepdims=True)
        self._session = onnx_session(models["clip_vision"])

    def embed(self, crops: list[Array]) -> Array:
        out = self._session.run(["image_embeds"], {"pixel_values": preprocess(crops)})[0]
        e = np.asarray(out, dtype=np.float32)
        norm: Array = e / np.linalg.norm(e, axis=1, keepdims=True)
        return norm

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        assert self._text is not None
        faces = faces_of(prior)[:MAX_FACES]
        if not faces:
            return Result(facts={"glasses": 0.0, "hats": 0.0, "age_groups": 0.0})
        rgb = rgb_array(frame)
        h, w = rgb.shape[:2]
        embeds = self.embed([f.crop for f in faces])
        g_keys, g_p = group_probs(embeds, self._text, "glasses")
        h_keys, h_p = group_probs(embeds, self._text, "hat")
        a_keys, a_p = group_probs(embeds, self._text, "age")
        del embeds  # never kept beyond this photo
        glasses = hats = 0
        generations: set[int] = set()
        boxes: list[Box] = []
        for i, face in enumerate(faces):
            notes: list[str] = []
            p_glasses = float(sum(g_p[i][j] for j, k in enumerate(g_keys) if k != "none"))
            if p_glasses >= GLASSES_MIN:
                glasses += 1
                sun = g_p[i][g_keys.index("sunglasses")] > g_p[i][g_keys.index("glasses")]
                notes.append("Sonnenbrille" if sun else "Brille")
            p_hat = float(sum(h_p[i][j] for j, k in enumerate(h_keys) if k != "none"))
            if p_hat >= HAT_MIN:
                hats += 1
                notes.append("Hut/Kappe")
            generations.add(GENERATION[a_keys[int(np.argmax(a_p[i]))]])
            if notes:
                x, y, fw, fh = face.box
                boxes.append(Box.from_pixels("face", x, y, fw, fh, (w, h), ", ".join(notes),
                                             max(p_glasses, p_hat)))  # fmt: skip
        facts = {"glasses": float(glasses), "hats": float(hats),
                 "age_groups": float(len(generations))}  # fmt: skip
        details = [
            ("Brillen", f"{glasses} (Schätzung)"),
            ("Hüte und Kappen", f"{hats} (Schätzung)"),
            ("Altersgruppen", ", ".join(GENERATION_NAMES[g] for g in sorted(generations))
             + " (Schätzung)"),
        ]  # fmt: skip
        return Result(facts=facts, boxes=boxes, details=details)


def create() -> TagsAnalyzer:
    return TagsAnalyzer()
