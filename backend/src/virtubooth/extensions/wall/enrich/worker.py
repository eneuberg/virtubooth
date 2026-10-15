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
- test images (`testjobs`) come before photos: answered in memory, never stored
- every photo is analysed ONCE (frozen, PLAN-NIGHT N3): no re-run when an
  analyzer version changes or an analyzer is switched on; only a crashed or
  failed attempt is retried (`jobs.MAX_ATTEMPTS`)
- per analyzer the heartbeat carries {processed, errors, avg_ms, last_ms},
  carried over from the previous heartbeat when the process is recycled
"""

from __future__ import annotations

import dataclasses
import logging
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Any

from PIL import Image

from ....core.clock import now_iso
from ....repositories.container import Repositories
from ....tools._common import open_repos
from . import jobs, models, testjobs
from .analyzers import ALWAYS_ON, INFOS, create_all, ml_installed, thread_limit
from .pipeline import (
    FRAME_SIDE,
    Analyzer,
    AnalyzerFailed,
    AnalyzerInfo,
    Frame,
    Outcome,
    PhotoInfo,
    Pipeline,
)

log = logging.getLogger("virtubooth.wall.enrich")

EXIT_RECYCLE = 75
MAX_PHOTOS = 200
MAX_RSS_MB = 900
IDLE_S = 2.0
NICE = 10
BEAT_S = 10.0
# the moving average of an analyzer's duration weighs about the last this many photos
AVG_WINDOW = 50

Stats = dict[str, float | int | None]


def tune_process(*, nice: bool = True) -> None:
    """Before numpy/onnxruntime are imported: few threads, low priority, no GUI."""
    if threads := thread_limit():
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    os.environ.setdefault("MPLBACKEND", "Agg")
    # onnxruntime >= 1.31 sends usage events to Microsoft unless told not to
    os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
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


def image_frame(image: Image.Image, photo: PhotoInfo) -> Frame:
    """A frame from an image in memory (test images)."""
    size = image.size
    rgb = image.convert("RGB")
    rgb.thumbnail((FRAME_SIDE, FRAME_SIDE), Image.Resampling.BILINEAR)
    return Frame(image=rgb, width=size[0], height=size[1], photo=photo)


# what a test image's frame says about its "photo" (taken now, see run_test)
TEST_PHOTO = PhotoInfo(
    id=0, public_id="testbild", extension="test", filename="testbild.jpg",
    created_at="1970-01-01T00:00:00.000+00:00", width=0, height=0, meta={},
    user_name="Testbild",
)  # fmt: skip


def _empty_stats() -> Stats:
    return {"processed": 0, "errors": 0, "avg_ms": None, "last_ms": None}


def _stats_from(beat: Mapping[str, Any]) -> dict[str, Stats]:
    """The previous heartbeat's per-analyzer stats (a recycled worker goes on)."""
    raw = beat.get("stats")
    out: dict[str, Stats] = {}
    if not isinstance(raw, dict):
        return out
    for name, st in raw.items():
        if not isinstance(st, dict):
            continue
        clean = _empty_stats()
        for key in clean:
            v = st.get(key)
            if isinstance(v, int | float) and not isinstance(v, bool):
                clean[key] = v
        out[str(name)] = clean
    return out


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
        self.tests = 0
        # analyzer → {processed, errors, avg_ms, last_ms} (the heartbeat's `stats`)
        self.stats: dict[str, Stats] = {}
        self._stats_loaded = False

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
        """Analyse one claimed photo, once; returns the new state."""
        db = repos.db
        path = repos.photos.path(photo.extension, photo.filename)
        if not path.is_file():
            jobs.skip(db, photo.id, "Fotodatei fehlt")
            return "skipped"
        # either/or: while the external AI detects objects the local detector rests
        ai_detect = jobs.ai_detection_active(repos.app_settings)
        # the AI cannot take it (no key, budget used up): the local detector does
        fallback = jobs.ai_detection_blocked(db, repos.app_settings) if ai_detect else None
        if fallback:
            ai_detect = False
            log.info("photo %s: local objects instead of the AI (%s)", photo.public_id, fallback)
        disabled = self._disabled(repos, opt_out=photo.opt_out)
        if ai_detect:
            disabled.add("objects")
        elif fallback and not photo.opt_out:
            # switched off for the AI (either/or): on for this one photo
            disabled.discard("objects")
        source = jobs.source_labels(repos.app_settings).get(photo.extension)
        if source is not None:
            photo = dataclasses.replace(photo, source=source)
        started = time.perf_counter()
        try:
            frame = load_frame(path, photo)
            frame.settings = jobs.analyzer_settings(repos.app_settings)
            outcome = self.pipeline.run(frame, disabled)
        except AnalyzerFailed as exc:
            self._count_error(exc.name)
            log.exception("analysis of photo %s failed in %s", photo.public_id, exc.name)
            cause = type(exc.__cause__).__name__ if exc.__cause__ else "Fehler"
            return jobs.fail(db, photo.id, f"Analyse fehlgeschlagen ({cause})")
        except Exception as exc:
            log.exception("analysis of photo %s failed", photo.public_id)
            return jobs.fail(db, photo.id, f"Analyse fehlgeschlagen ({type(exc).__name__})")
        data = outcome.data() | {"opt_out": photo.opt_out}
        if fallback:
            data[jobs.AI_FALLBACK] = fallback
        model, why = self._objects_model(outcome)
        if ai_detect and model is None:
            why = jobs.AI_ACTIVE
        jobs.finish(db, photo.id, facts=outcome.facts, data=data, versions=outcome.versions,
                    objects_found=outcome.objects, objects_model=model,
                    objects_skipped=why, ai_detect=ai_detect, image=photo.image)  # fmt: skip
        self._count(outcome)
        del frame
        release_memory()
        if report:
            total = (time.perf_counter() - started) * 1000
            parts = " ".join(f"{k}={v:.0f}" for k, v in outcome.timings_ms.items())
            report(
                f"{photo.public_id}: {total:.0f} ms ({parts}) rss={rss_mb():.0f} MB "
                f"facts={ {k: round(v, 2) for k, v in outcome.facts.items()} } "
                f"objects={len(outcome.objects)}"
            )
        return "done"

    def _objects_model(self, outcome: Outcome) -> tuple[str | None, str | None]:
        """(`photo_objects.model` of the local detector when it ran, else None
        and why it did not)."""
        names = [*outcome.object_sources, *(["objects"] if "objects" in outcome.versions else [])]
        for name in names:
            analyzer = next((a for a in self.pipeline.analyzers() if a.info.name == name), None)
            if analyzer is not None:
                return str(getattr(analyzer, "model_id", f"{name}@{analyzer.info.version}")), None
        return None, outcome.skipped.get("objects", "nicht verfügbar")

    def _count(self, outcome: Outcome) -> None:
        for name, ms in outcome.timings_ms.items():
            st = self.stats.setdefault(name, _empty_stats())
            n = int(st["processed"] or 0) + 1
            avg = st["avg_ms"]
            window = min(n, AVG_WINDOW)
            st["avg_ms"] = round(ms if avg is None else float(avg) + (ms - float(avg)) / window, 1)
            st["last_ms"] = round(ms, 1)
            st["processed"] = n

    def _count_error(self, name: str) -> None:
        st = self.stats.setdefault(name, _empty_stats())
        st["errors"] = int(st["errors"] or 0) + 1

    def _disabled(self, repos: Repositories, *, opt_out: bool) -> set[str]:
        disabled = jobs.disabled_analyzers(repos.app_settings)
        if opt_out:
            # „Meine Fotos nicht automatisch auswerten“: image values only
            disabled |= {i.name for i in INFOS if i.kind != "basic"}
        return disabled

    # -------------------------------------------------------- test images

    def run_test(self, repos: Repositories, image: Image.Image,
                 requested: Collection[str] | None) -> tuple[Outcome, PhotoInfo | None]:  # fmt: skip
        """The pipeline on a test image, in memory; nothing is stored."""
        names = {a.info.name for a in self.pipeline.analyzers()}
        enabled = names - jobs.disabled_analyzers(repos.app_settings)
        needs = {a.info.name: a.info.needs for a in self.pipeline.analyzers()}
        wanted = testjobs.wanted_analyzers(requested, enabled, needs) | set(ALWAYS_ON)
        frame = image_frame(image, dataclasses.replace(TEST_PHOTO, created_at=now_iso()))
        frame.settings = jobs.analyzer_settings(repos.app_settings)
        try:
            return self.pipeline.run(frame, names - wanted), None
        finally:
            del frame
            release_memory()

    def answer_tests(self, repos: Repositories) -> int:
        """Answer every waiting test image (they come before photos)."""
        folder = testjobs.requests_dir(self.data_dir)
        n = 0
        for rid in testjobs.pending(folder):
            if self.stop.is_set():
                break
            testjobs.answer(folder, rid, lambda img, req: self.run_test(repos, img, req))
            n += 1
        self.tests += n
        return n

    # --------------------------------------------------------- heartbeat

    def beat(self, repos: Repositories, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_beat < self.beat_s:
            return
        self._last_beat = now
        if not self._stats_loaded:
            # a recycled worker goes on counting where the last one stopped
            self._stats_loaded = True
            previous = _stats_from(repos.app_settings.get(jobs.WORKER_KEY))
            for name, st in self.stats.items():
                previous[name] = st
            self.stats = previous
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
            "stats": {k: dict(v) for k, v in self.stats.items()},
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
                self.answer_tests(repos)
                jobs.purge_deleted(db)
                use = jobs.analysis_image(repos.app_settings)
                photo = jobs.claim(db, use) if jobs.has_work(db) else None
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
