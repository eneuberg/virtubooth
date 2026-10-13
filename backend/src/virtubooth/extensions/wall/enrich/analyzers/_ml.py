"""Helpers the ML analyzers share (numpy, OpenCV, onnxruntime, MediaPipe).

Only the worker imports this, and only with the `ml` extra installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..pipeline import Frame, Result
from . import thread_limit

# numpy arrays, typed loosely: without the `ml` extra (CI) numpy's types are
# missing and mypy must still pass
Array = Any

if _threads := thread_limit():
    cv2.setNumThreads(_threads)  # OpenCV's own pool (YuNet, resizes)


@dataclass
class FaceCrop:
    """One face, in memory only (never stored)."""

    box: tuple[float, float, float, float]  # x, y, w, h in frame pixels
    score: float
    crop: Array  # enlarged square crop, RGB (landmarks, CLIP, age)
    tight: Array  # the detection box itself, RGB (FER+)
    blend: dict[str, float] | None = None  # MediaPipe blendshapes


def rgb_array(frame: Frame) -> Array:
    """The frame as a contiguous HxWx3 uint8 array (shared by all analyzers)."""
    cached = frame.cache.get("rgb")
    if cached is None:
        cached = np.ascontiguousarray(np.asarray(frame.image, dtype=np.uint8))
        frame.cache["rgb"] = cached
    arr: Array = cached
    return arr


def onnx_session(path: Path) -> Any:
    import onnxruntime as ort

    so = ort.SessionOptions()
    if threads := thread_limit():
        so.intra_op_num_threads = threads
    # idle pool threads sleep instead of spinning (they kept ~4 cores busy)
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False
    so.log_severity_level = 3
    # no second, pre-packed copy of the weights (-16 MB for FER+, same speed)
    so.add_session_config_entry("session.disable_prepacking", "1")
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def mp_image(rgb: Array) -> Any:
    import mediapipe as mp

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


def softmax(z: Array) -> Array:
    e = np.exp(z - z.max(axis=-1, keepdims=True))
    out: Array = e / e.sum(axis=-1, keepdims=True)
    return out


def crop(rgb: Array, box: tuple[float, float, float, float], scale: float = 1.0,
         square: bool = False) -> Array:  # fmt: skip
    """A region around `box` (x, y, w, h), grown by `scale`, clipped to the
    image; `square` uses the longer side. Edges are padded by replication so
    a face at the border keeps its size."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    bw, bh = w * scale, h * scale
    if square:
        bw = bh = max(bw, bh)
    x0, y0 = round(cx - bw / 2), round(cy - bh / 2)
    x1, y1 = round(cx + bw / 2), round(cy + bh / 2)
    ih, iw = rgb.shape[:2]
    pad = (max(0, -y0), max(0, y1 - ih), max(0, -x0), max(0, x1 - iw))
    part = rgb[max(0, y0) : min(ih, y1), max(0, x0) : min(iw, x1)]
    if part.size == 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    if any(pad):
        part = cv2.copyMakeBorder(part, *pad, cv2.BORDER_REPLICATE)
    return np.ascontiguousarray(part)


def faces_of(prior: Mapping[str, Result]) -> list[FaceCrop]:
    """The faces the `faces` analyzer left in its scratch (largest first)."""
    res = prior.get("faces")
    if res is None:
        return []
    faces: list[FaceCrop] = res.scratch.get("faces", [])
    return faces
