"""Validate uploaded JPEGs and re-encode them.

Re-encoding drops every byte the client chose (EXIF, GPS, XMP, ICC, comments,
trailing data, polyglot tricks) and gives ffmpeg uniform files later.

Decoding is bounded before it starts: the size comes from the header and is
checked (and capped by MAX_IMAGE_PIXELS) before the pixels are decoded, and a
progressive JPEG may have at most MAX_SCANS scans (each scan is another pass
over the whole image; a crafted file could have thousands).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from ..core.errors import ApiError

# hard ceiling for any decode, independent of extension policy (decompression bombs)
Image.MAX_IMAGE_PIXELS = 25_000_000
# Browsers' canvas.toBlob() writes baseline JPEGs (1 scan); progressive encoders
# use about 10. Counted as SOS marker bytes: entropy-coded data can't contain
# them (0xFF is always stuffed), so the count is an upper bound.
MAX_SCANS = 100
_SOS = b"\xff\xda"


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
    exact_size: tuple[int, int] | None = None,
) -> ProcessedImage:
    if not raw.startswith(b"\xff\xd8\xff"):
        raise _invalid("Nur JPEG-Bilder sind erlaubt.")
    try:
        img: Image.Image = Image.open(io.BytesIO(raw))
        if img.format != "JPEG":
            raise _invalid("Nur JPEG-Bilder sind erlaubt.")
        w, h = img.size
        if max(w, h) > max_side:
            raise _invalid(f"Bild ist zu groß (max. {max_side} px pro Seite).")
        if min(w, h) < min_side:
            raise _invalid("Bild ist zu klein.")
        if exact_size and (w, h) != tuple(exact_size):
            raise _invalid(f"Bild muss genau {exact_size[0]}×{exact_size[1]} px groß sein.")
        if raw.count(_SOS) > MAX_SCANS:
            raise _invalid()
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except ApiError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise _invalid() from exc

    # Pillow writes `info` back on save (the JPEG comment since 9.4; exif, icc,
    # xmp when asked): nothing the client sent may survive in either file
    img.info.clear()
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    thumb_img = img.copy()
    thumb_img.thumbnail((thumb_side, thumb_side), Image.Resampling.LANCZOS)
    thumb = io.BytesIO()
    thumb_img.save(thumb, "JPEG", quality=78, optimize=True)
    return ProcessedImage(out.getvalue(), thumb.getvalue(), img.width, img.height)
