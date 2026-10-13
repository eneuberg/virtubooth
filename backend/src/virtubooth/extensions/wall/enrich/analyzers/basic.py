"""`basic` „Bildwerte“: metadata and image values, Pillow only (always runs).

Facts: `brightness` 0..1 (mean luma), `colorfulness` (Hasler–Süsstrunk; ~0 grey,
>40 colourful, >80 very colourful), `sharpness` (variance of the Laplacian on a
512 px copy; blurred photos are low). All on a fixed 512 px size so photos of
any size compare.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from functools import cache
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .. import clock
from ..pipeline import Frame, Result
from . import BASIC

log = logging.getLogger("virtubooth.wall.enrich")

STAT_SIDE = 512
# the Laplacian, halved (scale 2) and shifted (offset 128) so it fits 8 bits
_LAPLACE = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=2, offset=128)


def brightness(img: Image.Image) -> float:
    return float(ImageStat.Stat(img.convert("L")).mean[0]) / 255.0


def colorfulness(img: Image.Image) -> float:
    """Hasler & Süsstrunk (2003): std and mean of the opponent channels
    rg = R - G and yb = (R + G) / 2 - B. Computed in 8-bit images (halved and
    shifted by 128, exact enough) so Pillow's C code does the work."""
    r, g, b = img.convert("RGB").split()
    rg = ImageChops.subtract(r, g, scale=2, offset=128)  # (R - G) / 2 + 128
    yb = ImageChops.subtract(ImageChops.add(r, g, scale=2), b, scale=2, offset=128)
    s_rg, s_yb = ImageStat.Stat(rg), ImageStat.Stat(yb)
    std = math.hypot(2 * s_rg.stddev[0], 2 * s_yb.stddev[0])
    mean = math.hypot(2 * (s_rg.mean[0] - 128), 2 * (s_yb.mean[0] - 128))
    return std + 0.3 * mean


def sharpness(img: Image.Image) -> float:
    lap = img.convert("L").filter(_LAPLACE)
    w, h = lap.size
    if w < 3 or h < 3:
        return 0.0
    # Pillow leaves the 1 px border unfiltered (raw pixel values): drop it
    inner = lap.crop((1, 1, w - 1, h - 1))
    return float((2 * ImageStat.Stat(inner).stddev[0]) ** 2)


@cache
def _extensions() -> dict[str, tuple[str, Mapping[str, str]]]:
    """id → (title, meta labels) of the installed extensions."""
    try:
        from ....sdk import discover_extensions

        return {e.id: (e.title, e.meta_labels) for e in discover_extensions()}
    except Exception:
        log.warning("extensions not loadable for the analysis details", exc_info=True)
        return {}


def _number(value: float) -> str:
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}".replace(".", ",")


class BasicAnalyzer:
    info = BASIC

    def load(self, models: Mapping[str, Path]) -> None:
        return None

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        small = frame.image.copy()
        small.thumbnail((STAT_SIDE, STAT_SIDE), Image.Resampling.BILINEAR)
        facts = {
            "brightness": round(brightness(small), 4),
            "colorfulness": round(colorfulness(small), 2),
            "sharpness": round(sharpness(small), 1),
        }
        photo = frame.photo
        title, labels = _extensions().get(photo.extension, (photo.extension, {}))
        details: list[tuple[str, str]] = [
            ("Aufgenommen", f"{clock.local(photo.created_at):%d.%m.%Y, %H:%M}"),
            ("Quelle", title),
        ]
        for key, value in photo.meta.items():
            if isinstance(value, str | int | float) and not isinstance(value, bool):
                details.append((labels.get(key, key), str(value)))
        details += [
            ("Gast", photo.user_name or "–"),
            ("Größe", f"{frame.width} × {frame.height} px"),
            ("Helligkeit", f"{facts['brightness'] * 100:.0f} %"),
            ("Farbigkeit", _number(facts["colorfulness"])),
            ("Schärfe", _number(facts["sharpness"])),
        ]
        return Result(facts=facts, details=details)


def create() -> BasicAnalyzer:
    return BasicAnalyzer()
