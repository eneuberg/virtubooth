"""Validate uploaded JPEGs and re-encode them.

Re-encoding drops every byte the client chose (EXIF, GPS, trailing data,
polyglot tricks) and gives ffmpeg uniform files later.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from .errors import ApiError

# hard ceiling for any decode, independent of extension policy (decompression bombs)
Image.MAX_IMAGE_PIXELS = 25_000_000


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    thumb: bytes
    width: int
    height: int


def _invalid(message: str = "Das Bild konnte nicht gelesen werden.") -> ApiError:
    return ApiError(400, "invalid_image", message)


def process_jpeg(
    raw: bytes,
    *,
    max_side: int,
    quality: int,
    thumb_side: int,
    min_side: int = 64,
) -> ProcessedImage:
    if not raw.startswith(b"\xff\xd8\xff"):
        raise _invalid("Nur JPEG-Bilder sind erlaubt.")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format != "JPEG":
            raise _invalid("Nur JPEG-Bilder sind erlaubt.")
        w, h = img.size
        if max(w, h) > max_side:
            raise _invalid(f"Bild ist zu groß (max. {max_side} px pro Seite).")
        if min(w, h) < min_side:
            raise _invalid("Bild ist zu klein.")
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except ApiError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise _invalid() from exc

    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    thumb_img = img.copy()
    thumb_img.thumbnail((thumb_side, thumb_side), Image.Resampling.LANCZOS)
    thumb = io.BytesIO()
    thumb_img.save(thumb, "JPEG", quality=78, optimize=True)
    return ProcessedImage(out.getvalue(), thumb.getvalue(), img.width, img.height)
