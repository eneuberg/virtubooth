"""The `basic` analyzer (Pillow only): brightness, colourfulness, sharpness, details."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw, ImageFilter

from virtubooth.extensions.wall.enrich.analyzers.basic import (
    BasicAnalyzer,
    brightness,
    colorfulness,
    sharpness,
)
from virtubooth.extensions.wall.enrich.pipeline import Frame, PhotoInfo


def checkerboard(size: int = 512, cell: int = 16) -> Image.Image:
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    for y in range(0, size, cell):
        for x in range((y // cell) % 2 * cell, size, 2 * cell):
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="black")
    return img


def stripes() -> Image.Image:
    img = Image.new("RGB", (480, 640))
    for i, c in enumerate([(255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 220, 0)]):
        img.paste(c, (0, i * 160, 480, (i + 1) * 160))
    return img


@pytest.mark.parametrize(
    ("img", "bright"),
    [
        (Image.new("RGB", (300, 200), "black"), 0.0),
        (Image.new("RGB", (300, 200), "white"), 1.0),
        (Image.new("RGB", (300, 200), (128, 128, 128)), 128 / 255),
    ],
)
def test_flat_images(img, bright):
    assert brightness(img) == pytest.approx(bright, abs=0.01)
    assert colorfulness(img) == pytest.approx(0, abs=0.5)
    assert sharpness(img) == pytest.approx(0, abs=0.01)


def test_colourful_beats_grey():
    assert colorfulness(stripes()) > 100
    assert colorfulness(Image.new("RGB", (100, 100), (200, 40, 40))) > 40  # one strong colour
    assert colorfulness(stripes().convert("L").convert("RGB")) < 1


def test_blur_lowers_sharpness():
    sharp = checkerboard()
    soft = sharp.filter(ImageFilter.GaussianBlur(3))
    blurred = sharp.filter(ImageFilter.GaussianBlur(8))
    assert sharpness(sharp) > 10 * sharpness(soft) > 10 * sharpness(blurred) > 0


def test_run_facts_and_details(monkeypatch):
    monkeypatch.setenv("VB_TIMEZONE", "Europe/Berlin")
    info = PhotoInfo(
        id=1, public_id="p", extension="booth", filename="x.jpg",
        created_at="2026-10-13T17:42:00.000+00:00", width=1080, height=1440,
        meta={"filter": "noir", "facing": "user"}, user_name="Tanzende Giraffe #1",
    )  # fmt: skip
    img = stripes()
    res = BasicAnalyzer().run(Frame(img, 1080, 1440, info), {})
    assert set(res.facts) == {"brightness", "colorfulness", "sharpness"}
    assert res.facts["colorfulness"] > 100
    details = dict(res.details)
    assert details["Aufgenommen"] == "13.10.2026, 19:42"
    assert details["Quelle"] == "Fotobox"  # the extension's title
    assert details["Filter"] == "noir" and details["Kamera"] == "user"  # meta_labels
    assert details["Gast"] == "Tanzende Giraffe #1"
    assert details["Größe"] == "1080 × 1440 px"
    assert not res.boxes and not res.scratch
