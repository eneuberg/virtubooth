"""„Modelle herunterladen“ in the admin: the missing model files, fetched by
the app process in a background thread.

Only files from the registry (`models.REGISTRY`: versioned URLs, pinned
SHA256) are ever downloaded; the client names nothing. They go to
`models.default_dest` (`$VB_WALL_MODELS_DIR` or `<data>/wall/models`), which
the worker searches before the baked-in `/opt/vb-models`, so it picks them up
with its next photo (no restart). One download at a time per folder; starting
it again while it runs, or when nothing is missing, changes nothing.
"""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from ....core.clock import now_iso
from . import models
from .models import ModelFile

log = logging.getLogger("virtubooth.wall.enrich")

DownloadState = Literal["idle", "running", "done", "failed"]
# keep this much free on top of VB_MIN_FREE_MB (the .part file, SQLite growth)
DISK_MARGIN = 64 * 1024 * 1024

HINT_NETWORK = (
    "Der Server braucht Zugriff auf huggingface.co und storage.googleapis.com. "
    "Alternativ das Image mit VB_BAKE_MODELS=1 bauen (Modelle im Image)."
)


@dataclass(frozen=True)
class Progress:
    state: DownloadState = "idle"
    # the model being downloaded right now
    current: str | None = None
    models: tuple[str, ...] = ()
    done_bytes: int = 0
    total_bytes: int = 0
    error: str | None = None  # German
    finished_at: str | None = None


def _free_bytes(folder: Path) -> int:
    """Free space where `folder` is (or would be created)."""
    probe = folder
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


@dataclass
class Downloader:
    dest: Path
    _progress: Progress = field(default_factory=Progress)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: threading.Thread | None = None

    def progress(self) -> Progress:
        with self._lock:
            return self._progress

    def _set(self, **changes: object) -> None:
        with self._lock:
            self._progress = replace(self._progress, **changes)  # type: ignore[arg-type]

    def _add(self, n: int) -> None:
        with self._lock:
            p = self._progress
            self._progress = replace(p, done_bytes=p.done_bytes + n)

    def start(self, wanted: Sequence[ModelFile], *, min_free_bytes: int = 0,
              wait: bool = False) -> bool:  # fmt: skip
        """Download `wanted` (registry entries) in a thread. False: one is
        already running or `wanted` is empty (nothing changes). `wait`: in
        this thread (tests, CLI)."""
        if not wanted:
            return False
        with self._lock:
            if self._progress.state == "running":
                return False
            self._progress = Progress(
                state="running", models=tuple(m.name for m in wanted),
                total_bytes=sum(m.size for m in wanted),
            )  # fmt: skip
        if wait:
            self._run(list(wanted), min_free_bytes)
            return True
        self._thread = threading.Thread(
            target=self._run, args=(list(wanted), min_free_bytes), name="wall-models",
            daemon=True,
        )  # fmt: skip
        self._thread.start()
        return True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, wanted: list[ModelFile], min_free_bytes: int) -> None:
        try:
            need = sum(m.size for m in wanted)
            free = _free_bytes(self.dest)
            if free - need < min_free_bytes + DISK_MARGIN:
                self._fail(
                    f"Zu wenig freier Speicher: {free / 1e6:.0f} MB frei, gebraucht werden "
                    f"{need / 1e6:.0f} MB plus die Reserve (VB_MIN_FREE_MB)."
                )
                return
            for model in wanted:
                self._set(current=model.name)
                path = self.dest / model.file
                if path.is_file() and models.sha256_of(path) == model.sha256:
                    self._add(model.size)
                    continue
                models.download(model, self.dest, log=log.info, progress=self._add)
        except models.FetchError as exc:
            log.warning("model download failed: %s", exc)
            self._fail(f"Herunterladen fehlgeschlagen ({exc}). {HINT_NETWORK}")
            return
        except OSError as exc:
            log.warning("model download failed: %s", exc)
            self._fail(
                f"Der Modellordner {self.dest} ist nicht beschreibbar "
                f"({exc.strerror or type(exc).__name__})."
            )
            return
        except Exception as exc:  # never kill the thread silently
            log.exception("model download failed")
            self._fail(f"Herunterladen fehlgeschlagen ({type(exc).__name__}).")
            return
        log.info("models downloaded into %s: %s", self.dest, ", ".join(m.name for m in wanted))
        self._set(state="done", current=None, finished_at=now_iso())

    def _fail(self, message: str) -> None:
        self._set(state="failed", current=None, error=message, finished_at=now_iso())


# one per folder, for the app's lifetime (the service may be recreated)
_downloaders: dict[Path, Downloader] = {}
_downloaders_lock = threading.Lock()


def for_dest(dest: Path) -> Downloader:
    key = dest.expanduser().absolute()
    with _downloaders_lock:
        found = _downloaders.get(key)
        if found is None:
            found = _downloaders[key] = Downloader(key)
        return found
