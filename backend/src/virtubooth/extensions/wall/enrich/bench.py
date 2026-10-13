"""`python -m virtubooth.extensions.wall.enrich bench PHOTO_DIR`: how fast and how
big the analysis is on this machine (run it on the Pi before a party).

Runs the real per-photo path (decode + downscale to 1280 px, then the pipeline)
over every JPEG in PHOTO_DIR, `--passes` times, in this process: the first
photo of the first pass is "cold" (models load lazily), later passes are warm.
No database. Per analyzer: load time, RSS after loading, threads it started,
warm median per photo and the CPU it used (process CPU time / wall time ≈ busy
cores). Uses the worker's settings (nice 10, $VB_WALL_THREADS, default 3)
unless `--no-nice`.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import models
from .analyzers import create_all, ml_installed, thread_limit
from .pipeline import Analyzer, AnalyzerInfo, Frame, PhotoInfo, Pipeline, Result
from .worker import load_frame, peak_rss_mb, release_memory, rss_mb


def _threads() -> int:
    try:
        return len(os.listdir("/proc/self/task"))
    except OSError:
        return 0


@dataclass
class Probe:
    """Wraps an analyzer and measures it."""

    inner: Analyzer
    load_s: float = 0.0
    rss_after_load: float = 0.0
    peak_after_load: float = 0.0
    threads_started: int = 0
    runs: list[tuple[int, float, float]] = field(default_factory=list)  # (pass, wall, cpu)
    current_pass: int = 0

    @property
    def info(self) -> AnalyzerInfo:
        return self.inner.info

    def load(self, paths: Mapping[str, Path]) -> None:
        threads, started = _threads(), time.perf_counter()
        self.inner.load(paths)
        self.load_s = time.perf_counter() - started
        self.rss_after_load, self.peak_after_load = rss_mb(), peak_rss_mb()
        self.threads_started = _threads() - threads

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        wall, cpu = time.perf_counter(), time.process_time()
        res = self.inner.run(frame, prior)
        self.runs.append((self.current_pass, time.perf_counter() - wall, time.process_time() - cpu))
        return res


def run_bench(photos: list[Path], *, with_age: bool, passes: int = 2,
              data_dir: Path | None = None) -> dict[str, Any]:  # fmt: skip
    probes = [Probe(a) for a in create_all()]
    ml = ml_installed()
    pipeline = Pipeline(
        probes,
        gate=lambda info: None if info.kind == "basic" or ml else "KI-Paket fehlt",
        resolve=models.resolver(data_dir),
    )
    disabled = set() if with_age else {"age"}
    per_photo: list[dict[str, float]] = []
    skipped: dict[str, str] = {}
    started_all = time.perf_counter()
    for n in range(passes):
        for probe in probes:
            probe.current_pass = n
        for i, path in enumerate(photos):
            wall, cpu = time.perf_counter(), time.process_time()
            info = PhotoInfo(i, path.stem, "bench", path.name, "2026-01-01T00:00:00+00:00", 0, 0,
                             {}, "Bench")  # fmt: skip
            frame = load_frame(path, info)
            decode = time.perf_counter() - wall
            outcome = pipeline.run(frame, disabled)
            skipped = outcome.skipped
            del frame
            release_memory()
            per_photo.append({
                "pass": n, "total_ms": (time.perf_counter() - wall) * 1000,
                "decode_ms": decode * 1000, "cpu_ms": (time.process_time() - cpu) * 1000,
            })  # fmt: skip
    elapsed = time.perf_counter() - started_all
    warm = [p for p in per_photo if p["pass"] > 0] or per_photo[1:] or per_photo
    analyzers = []
    for p in probes:
        hot = [r for r in p.runs if r[0] > 0] or p.runs
        if not hot:
            continue
        wall_sum, cpu_sum = sum(r[1] for r in hot), sum(r[2] for r in hot)
        analyzers.append({
            "name": p.info.name, "load_s": round(p.load_s, 3),
            "rss_after_load_mb": round(p.rss_after_load), "peak_after_load_mb": round(p.peak_after_load),
            "threads_started": p.threads_started,
            "warm_median_ms": round(statistics.median(r[1] for r in hot) * 1000, 1),
            "cold_first_ms": round(p.runs[0][1] * 1000, 1),
            "cpu_cores": round(cpu_sum / wall_sum, 2) if wall_sum else 0.0,
        })  # fmt: skip
    warm_total = [p["total_ms"] for p in warm]
    return {
        "photos": len(photos), "passes": passes, "with_age": with_age,
        "thread_limit": thread_limit(), "nice": os.nice(0), "ml": ml,
        "skipped": skipped, "analyzers": analyzers,
        "cold_first_photo_ms": round(per_photo[0]["total_ms"]),
        "warm_median_ms": round(statistics.median(warm_total)),
        "warm_mean_ms": round(statistics.fmean(warm_total)),
        "decode_median_ms": round(statistics.median(p["decode_ms"] for p in warm), 1),
        "warm_cpu_cores": round(sum(p["cpu_ms"] for p in warm) / sum(warm_total), 2),
        "photos_per_minute": round(60_000 / statistics.fmean(warm_total), 1),
        "peak_rss_mb": round(peak_rss_mb()), "rss_end_mb": round(rss_mb()),
        "threads_end": _threads(), "elapsed_s": round(elapsed, 1),
    }  # fmt: skip


def render(r: Mapping[str, Any]) -> str:
    lines = [
        f"{r['photos']} photos x {r['passes']} passes, age {'on' if r['with_age'] else 'off'}, "
        f"threads {r['thread_limit'] or 'default'}, nice {r['nice']}",
        f"{'analyzer':10} {'load s':>7} {'RSS MB':>7} {'threads':>7} {'cold ms':>8} "
        f"{'warm ms':>8} {'cores':>6}",
    ]
    for a in r["analyzers"]:
        lines.append(
            f"{a['name']:10} {a['load_s']:7.2f} {a['rss_after_load_mb']:7} "
            f"{a['threads_started']:7} {a['cold_first_ms']:8.0f} {a['warm_median_ms']:8.1f} "
            f"{a['cpu_cores']:6.2f}"
        )
    lines += [
        f"photo: cold {r['cold_first_photo_ms']} ms (with model loading), warm median "
        f"{r['warm_median_ms']} ms (decode {r['decode_median_ms']} ms), "
        f"{r['warm_cpu_cores']} cores busy",
        f"backfill: {r['photos_per_minute']} photos/min; peak RSS {r['peak_rss_mb']} MB, "
        f"{r['threads_end']} threads",
    ]
    if r["skipped"]:
        lines.append(f"skipped: {json.dumps(r['skipped'], ensure_ascii=False)}")
    return "\n".join(lines)
