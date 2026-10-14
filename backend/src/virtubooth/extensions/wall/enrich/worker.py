"""The analysis worker: a separate process, one photo at a time.

Started by the app's supervisor (`python -m virtubooth.extensions.wall.enrich
worker --data-dir …`, stdin a pipe) or by hand. It opens the database like the
CLI tools, runs at nice 10 with 3 threads, claims the newest photo that needs
analysis, runs the pipeline and stores the result. Idle: a DB scan every 2 s.

- heartbeat every 10 s in the settings key `x.wall.worker`
- stdin is a pipe and reaches EOF (the app died or stopped it) → exits
- SIGTERM / SIGINT → finishes the current photo, exits 0
- after 200 photos or above 900 MB RSS → exits 75; the supervisor restarts
  it at once (a fresh process returns memory that fragmentation keeps)
"""

from __future__ import annotations

import logging
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType
from typing import Any

from PIL import Image

from ....core.clock import now_iso
from ....repositories.container import Repositories
from ....tools._common import open_repos
from . import jobs, models
from .analyzers import INFOS, create_all, ml_installed, thread_limit
from .pipeline import FRAME_SIDE, Analyzer, AnalyzerInfo, Frame, PhotoInfo, Pipeline

log = logging.getLogger("virtubooth.wall.enrich")

EXIT_RECYCLE = 75
MAX_PHOTOS = 200
MAX_RSS_MB = 900
IDLE_S = 2.0
NICE = 10
BEAT_S = 10.0


def tune_process(*, nice: bool = True) -> None:
    """Before numpy/onnxruntime are imported: few threads, low priority, no GUI."""
    if threads := thread_limit():
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MPLBACKEND", "Agg")
    if nice:
        try:
            os.nice(NICE)
        except OSError:
            pass


def _proc_status_kb(field: str) -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def rss_mb() -> float:
    return _proc_status_kb("VmRSS") / 1024


def peak_rss_mb() -> float:
    return _proc_status_kb("VmHWM") / 1024


def release_memory() -> None:
    """Hand freed heap back to the OS (glibc keeps it otherwise; ~20-40 MB
    after model loading and between photos)."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def load_frame(path: Path, photo: PhotoInfo) -> Frame:
    with Image.open(path) as img:
        img.draft("RGB", (FRAME_SIDE, FRAME_SIDE))  # JPEG: decode at a reduced scale
        size = (photo.width, photo.height) if photo.width and photo.height else img.size
        rgb = img.convert("RGB")
    rgb.thumbnail((FRAME_SIDE, FRAME_SIDE), Image.Resampling.BILINEAR)
    return Frame(image=rgb, width=size[0], height=size[1], photo=photo)


class Worker:
    def __init__(
        self,
        data_dir: Path,
        *,
        max_photos: int = MAX_PHOTOS,
        max_rss_mb: float = MAX_RSS_MB,
        idle_s: float = IDLE_S,
        beat_s: float = BEAT_S,
        analyzers: Sequence[Analyzer] | None = None,
        watch_parent: bool = True,
    ) -> None:
        self.data_dir = data_dir
        self.max_photos = max_photos
        self.max_rss_mb = max_rss_mb
        self.idle_s = idle_s
        self.beat_s = beat_s
        self.stop = threading.Event()
        self._analyzers = analyzers
        self.watch_parent = watch_parent
        self._pipeline: Pipeline | None = None
        self._last_beat = 0.0
        self.processed = 0

    # ---------------------------------------------------------- pipeline

    @property
    def pipeline(self) -> Pipeline:
        if self._pipeline is None:
            resolve = models.resolver(self.data_dir)
            ml = ml_installed()

            def gate(info: AnalyzerInfo) -> str | None:
                return None if info.kind == "basic" or ml else "KI-Paket fehlt"

            analyzers = self._analyzers if self._analyzers is not None else create_all()
            self._pipeline = Pipeline(analyzers, gate=gate, resolve=resolve)
        return self._pipeline

    def process(self, repos: Repositories, photo: PhotoInfo,
                report: Callable[[str], None] | None = None) -> str:  # fmt: skip
        """Analyse one claimed photo; returns the new state."""
        db = repos.db
        path = repos.photos.path(photo.extension, photo.filename)
        if not path.is_file():
            jobs.skip(db, photo.id, "Fotodatei fehlt")
            return "skipped"
        disabled = jobs.disabled_analyzers(repos.app_settings)
        if photo.opt_out:
            # „Meine Fotos nicht automatisch auswerten“: image values only
            disabled |= {i.name for i in INFOS if i.kind != "basic"}
        started = time.perf_counter()
        try:
            frame = load_frame(path, photo)
            outcome = self.pipeline.run(frame, disabled)
        except Exception as exc:
            log.exception("analysis of photo %s failed", photo.public_id)
            return jobs.fail(db, photo.id, f"Analyse fehlgeschlagen ({type(exc).__name__})")
        jobs.finish(db, photo.id, facts=outcome.facts, data=outcome.data(),
                    versions=outcome.versions)  # fmt: skip
        del frame
        release_memory()
        if report:
            total = (time.perf_counter() - started) * 1000
            parts = " ".join(f"{k}={v:.0f}" for k, v in outcome.timings_ms.items())
            report(
                f"{photo.public_id}: {total:.0f} ms ({parts}) rss={rss_mb():.0f} MB "
                f"facts={ {k: round(v, 2) for k, v in outcome.facts.items()} }"
            )
        return "done"

    # --------------------------------------------------------- heartbeat

    def beat(self, repos: Repositories, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_beat < self.beat_s:
            return
        self._last_beat = now
        beat_at = now_iso()
        value = {
            "pid": os.getpid(),
            "beat_at": beat_at,
            "ml": ml_installed(),
            # all of them, also of disabled analyzers (the admin sees it before enabling)
            "models_missing": models.missing([m.name for m in models.REGISTRY], self.data_dir),
            "load_errors": dict(self._pipeline.load_errors) if self._pipeline else {},
            "processed": self.processed,
            "rss_mb": round(rss_mb()),
        }
        try:
            repos.app_settings.put(jobs.WORKER_KEY, value, at=beat_at)
        except Exception:
            log.warning("heartbeat failed", exc_info=True)

    # -------------------------------------------------------------- loop

    def _watch_parent(self) -> None:
        """stdin is the supervisor's pipe: EOF means the app is gone."""
        try:
            mode = os.fstat(0).st_mode
        except OSError:
            return
        if not stat.S_ISFIFO(mode):
            return

        def wait_eof() -> None:
            try:
                while sys.stdin.buffer.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            log.info("parent gone (stdin closed): stopping")
            self.stop.set()

        threading.Thread(target=wait_eof, name="parent-watch", daemon=True).start()

    def _on_signal(self, signum: int, _frame: FrameType | None) -> None:
        self.stop.set()

    def run(self, *, once: bool = False, limit: int | None = None,
            report: Callable[[str], None] | None = None) -> int:  # fmt: skip
        """The worker loop. `once`: work off what is pending (at most `limit`
        photos), then return; no parent watch, no recycling."""
        handlers: dict[int, Any] = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, self._on_signal)
        try:
            if not once and self.watch_parent:
                self._watch_parent()
            return self._loop(once=once, limit=limit, report=report)
        finally:
            for signum, old in handlers.items():
                signal.signal(signum, old)

    def _loop(self, *, once: bool, limit: int | None,
              report: Callable[[str], None] | None) -> int:  # fmt: skip
        with open_repos(self.data_dir) as repos:
            db = repos.db
            recovered = jobs.recover_stale(db)
            if recovered:
                log.info("recovered %d interrupted analyses", recovered)
            self.beat(repos, force=True)
            while not self.stop.is_set():
                self.beat(repos)
                jobs.purge_deleted(db)
                photo = jobs.claim(db) if jobs.has_work(db) else None
                if photo is None:
                    if once:
                        break
                    self.stop.wait(self.idle_s)
                    continue
                self.process(repos, photo, report)
                self.processed += 1
                if once:
                    if limit is not None and self.processed >= limit:
                        break
                    continue
                if self.processed >= self.max_photos or rss_mb() > self.max_rss_mb:
                    log.info("recycling after %d photos (%.0f MB RSS)", self.processed, rss_mb())
                    self.beat(repos, force=True)
                    return EXIT_RECYCLE
            self.beat(repos, force=True)
        return 0
