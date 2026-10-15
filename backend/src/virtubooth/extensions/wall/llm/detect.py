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
after the local ones (idx continues). Each source runs once per photo.

The local detector as fallback: a queued photo the AI cannot deliver goes back
to the worker, which adds the local detector's list (`jobs.hand_to_local`; the
AI's run is recorded `skipped`/`failed` with the reason, so it is never sent
later). Immediately while no key is usable, the provider rejected the key
(401/403; remembered for that key until it changes, a key test passes or
AUTH_RETRY_S passed) or the budget is used up: every queued photo. For an
error about one photo (unreadable, bad answer, refusal): that photo. Provider
trouble (network, 5xx, 429) is retried every BACKOFF_S; a photo that has been
failing for FALLBACK_AFTER_S falls back, and while the trouble lasts that long
every other queued photo does too, only the newest is still tried (it tells
when the provider is back). Once it is, new photos go to the AI again; photos
that fell back keep their local list.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from PIL import Image, ImageOps

from ..enrich import jobs
from ..enrich.objects import has_run
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
# provider trouble this long (since a photo's first failure): local detector
FALLBACK_AFTER_S = 300.0
# a rejected key is tried again after this long (also at once when it changes)
AUTH_RETRY_S = 300.0
# photos handed back per step
HANDOVER_BATCH = 50


@dataclass(frozen=True)
class _Photo:
    id: int
    public_id: str
    path_ext: str
    filename: str
    image: str


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
        self.clock: Callable[[], float] = time.monotonic
        # provider trouble: since when (current streak), and per photo its first failure
        self.trouble_since: float | None = None
        self._first_failure: dict[int, float] = {}
        # (fingerprint of the key the provider rejected, when)
        self._rejected: tuple[str, float] | None = None
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
            # „Erkennung auf“ (as the local analysis): the original when there is one,
            # or the filtered photo
            "SELECT p.id, p.public_id, p.extension, p.filename, p.raw_filename FROM photos p "
            "JOIN users u ON u.id = p.user_id WHERE p.id = ? AND p.deleted_at IS NULL "
            "AND p.hidden_at IS NULL AND u.ai_opt_out = 0 AND u.analysis_opt_out = 0 "
            "AND u.banned_at IS NULL",
            (photo_id,),
        )
        if row is None:
            return None
        use = jobs.analysis_image(self.service.core.repos.app_settings)
        filename, image = jobs.pick_image(use, row["filename"], row["raw_filename"])
        return _Photo(row["id"], row["public_id"], row["extension"], filename, image)

    @staticmethod
    def _fingerprint(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def key_ok(self) -> None:
        """The key works (a key test passed): forget that the provider rejected it."""
        self._rejected = None

    def _outage(self) -> bool:
        return (
            self.trouble_since is not None and self.clock() - self.trouble_since >= FALLBACK_AFTER_S
        )

    def _unable(self, cfg: LlmConfig) -> tuple[str, str] | None:
        """Why no queued photo can go to the AI now: (short reason, detail), None
        while they can (provider trouble aside: that shows per call)."""
        svc = self.service
        key = svc.keys.load(cfg.provider)
        if key is None:
            status = svc.keys.status()
            if status.set and not status.valid:
                return jobs.KEY_INVALID, "Schlüssel nicht lesbar."
            return jobs.NO_KEY, "Kein API-Schlüssel gesetzt."
        if self._rejected is not None:
            fingerprint, at = self._rejected
            if fingerprint == self._fingerprint(key) and self.clock() - at < AUTH_RETRY_S:
                return jobs.KEY_INVALID, "Der API-Schlüssel wurde abgelehnt."
            self._rejected = None
        blocked = svc.blocked_reason(cfg)
        if blocked is not None:
            return jobs.BUDGET, blocked
        return None

    def fallback_now(self) -> str | None:
        """While the AI is the detector but the local one stands in (the reason)."""
        cfg = self.service.config()
        if not self.active(cfg):
            return None
        why = self._unable(cfg)
        if why is not None:
            return why[0]
        return jobs.UNREACHABLE if self._outage() else None

    def run_once(self) -> str:
        """One step: `idle` (nothing to do or switched off), `done` (one photo
        handled, or photos handed to the local detector), `blocked` (budget, with
        nothing to hand back) or `backoff` (provider trouble)."""
        from .service import Unavailable

        svc = self.service
        cfg = svc.config()
        if not self.active(cfg):
            self.blocked = None
            return "idle"
        source = PROVIDERS[cfg.provider].source
        db = svc.core.db
        unable = self._unable(cfg)
        self.blocked = unable[1] if unable is not None and unable[0] == jobs.BUDGET else None
        ids = ports.eligible_for_external(db, source, HANDOVER_BATCH)
        if not ids:
            return "blocked" if self.blocked else "idle"
        if unable is not None:
            # the AI cannot take any: every queued photo gets the local detector
            handed = [
                self._hand_over(pid, source, "skipped", None, unable[1], unable[0]) for pid in ids
            ]
            if any(handed):
                return "done"
            return "blocked" if self.blocked else "idle"
        if self._outage():
            # the provider has been failing for minutes: only the newest is still tried
            for pid in ids[1:]:
                self._hand_over(pid, source, "failed", cfg.model,
                                self.last_error or jobs.UNREACHABLE, jobs.UNREACHABLE)  # fmt: skip
        photo = self._sendable(ids[0])
        if photo is None:
            # opted out or hidden since the query: never sent, looked at again later
            return "idle"
        first = self._first_failure.get(photo.id)
        if first is not None and self.clock() - first >= FALLBACK_AFTER_S:
            self._hand_over(photo.id, source, "failed", cfg.model,
                            self.last_error or jobs.UNREACHABLE, jobs.UNREACHABLE, photo.image)  # fmt: skip
            return "done"
        try:
            raw = svc.core.repos.photos.path(photo.path_ext, photo.filename).read_bytes()
            image = downscale(raw, cfg.image_max_px)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            log.warning("llm detect: photo %s unreadable: %s", photo.public_id, exc)
            self._hand_over(photo.id, source, "failed", None, "Foto nicht lesbar.",
                            jobs.PHOTO_FAILED, photo.image)  # fmt: skip
            return "done"
        self.running = True
        try:
            objs, _ = svc.call(
                "detect",
                photo.public_id,
                lambda p, m: p.detect(image, model=m, effort=cfg.effort),
                config=cfg,
            )
        except Unavailable:
            # key or budget changed since `_unable`: the next step hands the photos back
            return "done"
        except ProviderError as exc:
            if exc.kind == "auth":
                key = svc.keys.load(cfg.provider)
                if key is not None:
                    self._rejected = (self._fingerprint(key), self.clock())
                self.last_error = exc.message
                log.warning("llm detect: %s (local detector takes over)", exc.message)
                self._hand_over(photo.id, source, "failed", cfg.model, exc.message,
                                jobs.KEY_INVALID, photo.image)  # fmt: skip
                return "done"
            if exc.transient:
                now = self.clock()
                self.last_error = exc.message
                self._first_failure.setdefault(photo.id, now)
                if self.trouble_since is None:
                    self.trouble_since = now
                log.warning("llm detect: %s (retrying later)", exc.message)
                return "backoff"
            self._hand_over(photo.id, source, "failed", cfg.model, exc.message,
                            jobs.PHOTO_FAILED, photo.image)  # fmt: skip
            return "done"
        finally:
            self.running = False
        self.last_error = None
        self.trouble_since = None
        self._first_failure.clear()
        try:
            with db.tx():
                ports.append(db, photo.id, source, cfg.model, objs, image=photo.image)
                # either/or: the AI's list is the photo's list, the local run ends here
                if not has_run(db, photo.id, "local"):
                    ports.record_run(db, photo.id, "local", "skipped", None, jobs.AI_ACTIVE)
        except ports.FrozenError:
            log.info("llm detect: %s already ran for %s", source, photo.public_id)
        return "done"

    def _hand_over(
        self,
        photo_id: int,
        source: str,
        state: ports.RunState,
        model: str | None,
        error: str,
        reason: str,
        image: str | None = None,
    ) -> bool:
        """The AI cannot deliver this photo: its run is recorded as `state` with
        `error`, and the worker adds the local detector's list (`reason` shown).
        A photo whose local run is decided already (from before v16, or with both
        lists) cannot fall back: it stays queued, and only an error about the photo
        itself is recorded (as before). True when the photo left the queue."""
        db = self.service.core.db
        self._first_failure.pop(photo_id, None)
        try:
            with db.tx():
                if has_run(db, photo_id, "local"):
                    if reason != jobs.PHOTO_FAILED:
                        return False
                    ports.record_run(db, photo_id, source, state, model, error[:200], image=image)
                    return True
                ports.record_run(db, photo_id, source, state, model, error[:200], image=image)
                jobs.hand_to_local(db, photo_id, reason)
        except ports.FrozenError:
            return False
        log.info("llm detect: photo %d to the local detector (%s)", photo_id, reason)
        return True

    def _record(
        self,
        photo_id: int,
        source: str,
        state: ports.RunState,
        model: str | None,
        error: str,
        image: str | None = None,
    ) -> None:
        try:
            ports.record_run(
                self.service.core.db, photo_id, source, state, model, error[:200], image=image
            )
        except ports.FrozenError:
            pass
