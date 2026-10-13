"""`… enrich bench`: runs the real per-photo path over a folder (no database)."""

from __future__ import annotations

from PIL import Image

from virtubooth.extensions.wall.enrich.__main__ import main
from virtubooth.extensions.wall.enrich.bench import render, run_bench


def test_bench_reports_per_analyzer_and_totals(tmp_path, capsys):
    for i, colour in enumerate([(200, 30, 30), (20, 120, 220), (90, 90, 90)]):
        Image.new("RGB", (320, 240), colour).save(tmp_path / f"{i}.jpg")
    photos = sorted(tmp_path.glob("*.jpg"))
    # no models anywhere: the ML analyzers are skipped, basic always runs
    r = run_bench(photos, with_age=False, passes=2, data_dir=tmp_path)
    assert r["photos"] == 3 and r["passes"] == 2
    basic = next(a for a in r["analyzers"] if a["name"] == "basic")
    assert basic["warm_median_ms"] > 0 and basic["rss_after_load_mb"] > 0
    assert r["photos_per_minute"] > 0 and r["peak_rss_mb"] >= r["rss_end_mb"] > 0
    assert "basic" in render(r)
    assert main(["bench", str(tmp_path), "--passes", "1", "--no-nice", "--json"]) == 0
    assert '"photos": 3' in capsys.readouterr().out
