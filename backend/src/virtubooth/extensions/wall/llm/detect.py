"""Object detection by the external AI (PLAN-NIGHT N9), „Objekte mit KI“ in the
Modelle card: the pipeline's step for photos while it is the active detector.

Either/or with the local detector (config.DetectConfig): while `detect.external`
(and the master switch `enabled`) is on, the worker skips the local `objects`
analyzer and marks each photo it finishes (`wall_analysis.ai_detect`); this
runner sends exactly those photos. Photos finished before (or while the local
detector was active) are never sent: there is no backfill sweep. Its own usage
kind (`detect`); the AI's list is the photo's object list (the merged list holds
just that one source for new photos), which the poll then rates.

A thread in the main process, one photo at a time, while the AI detector is
active and a key is stored: the newest photo the pipeline marked and no AI has
seen yet → the guest's flags
are read again right before sending → the photo goes out downscaled (long
edge ≤ `image_max_px`, JPEG q80, no metadata) → its objects are appended
after the local ones (idx continues). Each source runs once per photo: a
failure about the photo (unreadable answer, refusal) is recorded as `failed`
and never retried; a failure about the provider (key, limit, network) is
not the photo's fault, so the runner backs off and tries again later.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from PIL import Image, ImageOps

from . import ports
from .providers import BY_ID as PROVIDERS
from .providers.base import ProviderError

if TYPE_CHECKING:
    from .config import LlmConfig
    from .service import LlmService

log = logging.getLogger("virtubooth.llm")

IDLE_S = 5.0
BUSY_S = 0.2
BACKOFF_S = 60.0
JPEG_QUALITY = 80


@dataclass(frozen=True)
class _Photo:
    id: int
    public_id: str
    path_ext: str
    filename: str


def downscale(raw: bytes, max_px: int) -> bytes:
    """JPEG, long edge ≤ max_px, quality 80, upright, no EXIF/ICC/comments."""
    with Image.open(io.BytesIO(raw)) as src:
        img = ImageOps.exif_transpose(src).convert("RGB")
    img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    img.info.clear()
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


DetectorState = Literal["off", "idle", "running", "blocked"]


class DetectionRunner:
    def __init__(self, service: LlmService) -> None:
        from .service import Ticker

        self.service = service
        self.last_error: str | None = None
        self.blocked: str | None = None
        self.running = False
        self._ticker = Ticker("llm-detect", self.step)

    def state(self) -> DetectorState:
        """For `GET /llm`: off (switched off or no key), running (a photo is out),
        blocked (budget) or idle."""
        svc = self.service
        cfg = svc.config()
        if not self.active(cfg) or svc.keys.load(cfg.provider) is None:
            return "off"
        if self.running:
            return "running"
        if self.blocked or svc.blocked_reason(cfg):
            return "blocked"
        return "idle"

    @staticmethod
    def active(cfg: LlmConfig) -> bool:
        return cfg.ai_detection and PROVIDERS[cfg.provider].vision

    def start(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def poke(self) -> None:
        self._ticker.poke()

    def step(self) -> float:
        outcome = self.run_once()
        if outcome == "done":
            return BUSY_S
        if outcome == "backoff":
            return BACKOFF_S
        return IDLE_S

    def _sendable(self, photo_id: int) -> _Photo | None:
        """The photo if it may leave the server right now (live flags)."""
        row = self.service.core.db.one(
            # the unfiltered original when there is one (as the local analysis)
            "SELECT p.id, p.public_id, p.extension, "
            "COALESCE(p.raw_filename, p.filename) AS filename FROM photos p "
            "JOIN users u ON u.id = p.user_id WHERE p.id = ? AND p.deleted_at IS NULL "
            "AND p.hidden_at IS NULL AND u.ai_opt_out = 0 AND u.analysis_opt_out = 0 "
            "AND u.banned_at IS NULL",
            (photo_id,),
        )
        if row is None:
            return None
        return _Photo(row["id"], row["public_id"], row["extension"], row["filename"])

    def run_once(self) -> str:
        """One photo: `idle` (nothing to do or switched off), `done` (one photo
        handled), `blocked` (budget) or `backoff` (provider trouble)."""
        from .service import Unavailable

        svc = self.service
        cfg = svc.config()
        if not self.active(cfg):
            self.blocked = None
            return "idle"
        if svc.keys.load(cfg.provider) is None:
            return "idle"
        source = PROVIDERS[cfg.provider].source
        db = svc.core.db
        ids = ports.eligible_for_external(db, source, 1)
        if not ids:
            return "idle"
        photo = self._sendable(ids[0])
        if photo is None:
            # opted out or hidden since the query: never sent, looked at again later
            return "idle"
        self.blocked = svc.blocked_reason(cfg)
        if self.blocked is not None:
            return "blocked"
        try:
            raw = svc.core.repos.photos.path(photo.path_ext, photo.filename).read_bytes()
            image = downscale(raw, cfg.image_max_px)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            log.warning("llm detect: photo %s unreadable: %s", photo.public_id, exc)
            self._record(photo.id, source, "failed", None, "Foto nicht lesbar.")
            return "done"
        self.running = True
        try:
            objs, _ = svc.call(
                "detect",
                photo.public_id,
                lambda p, m: p.detect(image, model=m, effort=cfg.effort),
                config=cfg,
            )
        except Unavailable as exc:
            self.blocked = exc.message if exc.code == "llm_budget_exhausted" else None
            return "blocked" if self.blocked else "idle"
        except ProviderError as exc:
            if exc.transient:
                self.last_error = exc.message
                log.warning("llm detect: %s (retrying later)", exc.message)
                return "backoff"
            self._record(photo.id, source, "failed", cfg.model, exc.message[:200])
            return "done"
        finally:
            self.running = False
        self.last_error = None
        try:
            ports.append(db, photo.id, source, cfg.model, objs)
        except ports.FrozenError:
            log.info("llm detect: %s already ran for %s", source, photo.public_id)
        return "done"

    def _record(
        self, photo_id: int, source: str, state: ports.RunState, model: str | None, error: str
    ) -> None:
        try:
            ports.record_run(self.service.core.db, photo_id, source, state, model, error[:200])
        except ports.FrozenError:
            pass
