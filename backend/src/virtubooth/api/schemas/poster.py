"""Request and response models of the poster template (`/api/admin/poster`).

The host's own PDF and where the QR code goes on it. The rectangle is relative
to the displayed page (0..1, origin top left, rotation applied); the server
checks it, the admin's browser renders and fills the poster.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PosterRect(BaseModel):
    """The QR field: relative to the page (0..1), origin top left, square in PDF points."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(description="Left edge, 0..1 of the page width.")
    y: float = Field(description="Top edge, 0..1 of the page height.")
    w: float = Field(description="Width, 0.03..1 of the page width.")
    h: float = Field(description="Height, 0.03..1 of the page height.")


class PosterTemplate(BaseModel):
    """The stored template. The layout fields are null until the first layout save."""

    sha256: str = Field(description="Hex SHA-256 of the PDF (a cache key for its bytes).")
    bytes: int = Field(description="Size of the PDF.")
    uploaded_at: str
    by: str = Field(description="Who uploaded it (audit actor).")
    pages: int | None = Field(description="Pages in the PDF, as the editor's PDF reader counted.")
    page: int | None = Field(description="The poster page, 0-based.")
    page_width: float | None = Field(description="That page's width in PDF points (rotated).")
    page_height: float | None = Field(description="That page's height in PDF points (rotated).")
    rect: PosterRect | None


class PosterOut(BaseModel):
    template: PosterTemplate | None
    max_bytes: int = Field(description="Largest PDF the server takes.")


class PosterLayoutIn(BaseModel):
    """Where the QR code goes. `pages` and the sizes come from the editor's PDF reader."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(description="0-based page index, below `pages`.")
    pages: int = Field(description="Pages in the PDF (1..500).")
    page_width: float = Field(description="PDF points, rotation applied (0 < w ≤ 14400).")
    page_height: float = Field(description="PDF points, rotation applied (0 < h ≤ 14400).")
    rect: PosterRect
