"""Upload burst (REQUIREMENTS §4): 20 guests × 3 uploads at once while the real
analysis worker runs (basic analyzers; ML too when the `ml` extra and the
models are there: $VB_WALL_MODELS_DIR). Every photo is analysed exactly once,
the worker never runs two photos at once, and uploads stay fast:
p95 with the worker ≤ 1.5 × p95 without + 100 ms.

Opt-in: `VB_PERF=1 uv run pytest tests/perf/test_upload_burst.py`. The CLI
prints the same numbers: `python -m virtubooth.extensions.wall.enrich burst`.
"""

from __future__ import annotations

import os

import pytest

from virtubooth.extensions.wall.enrich import burst, models

# read at import: the autouse clean_env fixture removes VB_* before each test
PERF = os.environ.get("VB_PERF", "").strip() == "1"
MODELS_DIR = os.environ.get(models.MODELS_ENV, "")

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(not PERF, reason="opt-in: VB_PERF=1"),
]


def test_upload_burst(monkeypatch, tmp_path):
    if MODELS_DIR:
        monkeypatch.setenv(models.MODELS_ENV, MODELS_DIR)
    result = burst.compare(20, 60, data_dir=tmp_path, log=print)
    print(burst.render(result))
    without, with_ = result["without_worker"], result["with_worker"]
    assert without["uploads"] == with_["uploads"] == 60
    assert without["errors"] == with_["errors"] == 0
    # analysed exactly once: one attempt each, one local run each
    assert with_["drain_s"] is not None
    assert with_["analysed"] == 60 and with_["attempts"] == {1: 60}
    assert with_["local_runs"] == 60
    # one photo at a time
    assert with_["max_running"] <= 1
    assert result["p95_ok"], result
