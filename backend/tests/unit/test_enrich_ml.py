"""Each ML analyzer loads its model and runs on a blank frame. Skipped unless
the `ml` extra is installed and the models are present ($VB_WALL_MODELS_DIR
when pytest starts, or /opt/vb-models; `models fetch --with-age`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from virtubooth.extensions.wall.enrich import models
from virtubooth.extensions.wall.enrich.analyzers import BY_NAME, create, ml_installed
from virtubooth.extensions.wall.enrich.pipeline import Frame, PhotoInfo, Result

# read at import: the autouse clean_env fixture removes VB_* before each test
DIRS = [Path(d) for d in [os.environ.get(models.MODELS_ENV, "")] if d] + [models.BAKED_DIR]
ML = ["faces", "emotion", "gestures", "objects", "tags", "age"]

pytestmark = pytest.mark.skipif(not ml_installed(), reason="needs the ml extra")


def blank() -> Frame:
    info = PhotoInfo(1, "p", "booth", "x.jpg", "2026-10-13T18:00:00.000+00:00", 640, 480, {}, "")
    return Frame(Image.new("RGB", (640, 480), (120, 110, 100)), 640, 480, info)


@pytest.mark.parametrize("name", ML)
def test_loads_and_runs_on_a_blank_frame(name):
    info = BY_NAME[name]
    paths = {m: models.find(m, DIRS) for m in info.models}
    if not all(paths.values()):
        pytest.skip(f"models missing: {[m for m, p in paths.items() if p is None]}")
    prior: dict[str, Result] = {}
    if "faces" in info.needs:
        faces = create("faces")
        faces.load({m: p for m in BY_NAME["faces"].models if (p := models.find(m, DIRS))})
        prior["faces"] = faces.run(blank(), {})
    analyzer = create(name)
    analyzer.load({m: p for m, p in paths.items() if p})
    res = analyzer.run(blank(), prior)
    assert set(res.facts) == set(info.facts)
    assert all(v == 0 for v in res.facts.values()), res.facts  # nothing on a blank frame
