"""`EnrichmentService`: what the wall (W1) and the admin API use (PLAN §4.5).

Constructed once per app as `EnrichmentService(core)`; `start()` spawns and
supervises the worker process, `stop()` ends it. Everything else reads the
database the worker writes, so it also works with a worker in another
container (`VB_WALL_WORKER=off` here, heartbeat in `x.wall.worker`).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from ....core.clock import now_iso
from . import categories, jobs, models
from .analyzers import ALWAYS_ON, BY_NAME, INFOS, ml_installed
from .categories import CategoryDef, CategoryWinners, PhotoFilter
from .schemas import (
    AnalysisBox,
    AnalysisCounts,
    AnalysisState,
    AnalysisStatus,
    AnalyzerStatus,
    DetailLine,
    PhotoAnalysis,
    WorkerState,
    WorkerStatus,
)
from .supervisor import Supervisor

if TYPE_CHECKING:
    from ....runtime import Core

__all__ = [
    "CategoryDef",
    "CategoryWinners",
    "EnrichmentService",
    "PhotoFilter",
    "PhotoSummary",
]

log = logging.getLogger("virtubooth.wall.enrich")

# a heartbeat older than this counts as gone (the worker beats every 10 s)
BEAT_FRESH_S = 35.0
_CHUNK = 500


@dataclass(frozen=True)
class PhotoSummary:
    state: str
    facts: Mapping[str, float]


_services: dict[int, EnrichmentService] = {}
_services_lock = threading.Lock()


def _age_s(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


class EnrichmentService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self.supervisor = Supervisor(core.settings.data_dir)
        with _services_lock:
            _services[id(core)] = self

    @classmethod
    def of(cls, core: Core) -> EnrichmentService:
        """The app's service (the one the wall extension made), else a new,
        unstarted one (the admin API without the wall's lifecycle, tests)."""
        with _services_lock:
            found = _services.get(id(core))
        if found is not None and found.core is core:
            return found
        return cls(core)

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        self.supervisor.start()

    def stop(self) -> None:
        self.supervisor.stop()

    # ------------------------------------------------------------ the port

    def summaries(self, photo_ids: Sequence[int]) -> dict[int, PhotoSummary]:
        """State and facts per photo (internal ids). A photo without a row is
        `pending`; unknown ids are left out."""
        ids = list(dict.fromkeys(int(i) for i in photo_ids))
        db = self.core.db
        states: dict[int, str] = {}
        facts: dict[int, dict[str, float]] = {}
        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start : start + _CHUNK]
            marks = ", ".join("?" for _ in chunk)
            for r in db.all(
                "SELECT p.id, COALESCE(a.state, 'pending') AS state FROM photos p "
                f"LEFT JOIN wall_analysis a ON a.photo_id = p.id WHERE p.id IN ({marks})",
                chunk,
            ):
                states[int(r["id"])] = r["state"]
            for r in db.all(
                f"SELECT photo_id, key, value FROM wall_facts WHERE photo_id IN ({marks})", chunk
            ):
                facts.setdefault(int(r["photo_id"]), {})[r["key"]] = float(r["value"])
        return {pid: PhotoSummary(state, facts.get(pid, {})) for pid, state in states.items()}

    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]:
        """Photos whose analysis changed after `rev`: (the new rev, photo ids),
        in change order, at most `limit` (call again while the list is full)."""
        rows = self.core.db.all(
            "SELECT photo_id, rev FROM wall_analysis WHERE rev > ? ORDER BY rev LIMIT ?",
            (rev, max(1, limit)),
        )
        if not rows:
            return rev, []
        return int(rows[-1]["rev"]), [int(r["photo_id"]) for r in rows]

    def catalogue(self) -> list[CategoryDef]:
        return list(categories.CATALOGUE)

    def winners(
        self, ids: Sequence[str], flt: PhotoFilter, per_category: int = 3
    ) -> list[CategoryWinners]:
        return categories.winners(self.core.db, ids, flt, per_category)

    # ------------------------------------------------------- admin helpers

    def heartbeat(self) -> dict[str, Any]:
        return self.core.repos.app_settings.get(jobs.WORKER_KEY)

    def disabled(self) -> set[str]:
        return jobs.disabled_analyzers(self.core.repos.app_settings)

    def _fresh_beat(self) -> dict[str, Any] | None:
        beat = self.heartbeat()
        age = _age_s(beat.get("beat_at"))
        return beat if age is not None and age <= BEAT_FRESH_S else None

    def analyzers(self) -> list[AnalyzerStatus]:
        disabled = self.disabled()
        beat = self._fresh_beat()
        ml = bool(beat["ml"]) if beat else ml_installed()
        if beat:
            missing = set(beat.get("models_missing") or [])
        else:
            missing = set(
                models.missing([m.name for m in models.REGISTRY], self.core.settings.data_dir)
            )
        load_errors: dict[str, str] = dict(beat.get("load_errors") or {}) if beat else {}
        out: dict[str, AnalyzerStatus] = {}
        for info in INFOS:  # registry order is a valid dependency order
            reason: str | None = None
            if info.kind == "ml" and not ml:
                reason = "Braucht das KI-Paket (Docker-Image mit VB_ML=1)."
            elif lacking := [m for m in info.models if m in missing]:
                reason = f"Modell fehlt: {', '.join(lacking)} (Befehl „models fetch“)."
            elif info.name in load_errors:
                reason = "Konnte nicht geladen werden (siehe Server-Log)."
            else:
                for need in info.needs:
                    dep = out.get(need)
                    if dep is None or not dep.enabled or not dep.available:
                        reason = f"Braucht die Analyse „{BY_NAME[need].title}“."
                        break
            out[info.name] = AnalyzerStatus(
                name=info.name, title=info.title, kind=info.kind, version=info.version,
                enabled=info.name not in disabled, available=reason is None, reason=reason,
                facts=list(info.facts),
            )  # fmt: skip
        return list(out.values())

    def active_analyzers(self) -> set[str]:
        """Enabled and able to run: what `CategoryDef.available()` wants."""
        return {a.name for a in self.analyzers() if a.enabled and a.available}

    def worker(self) -> WorkerStatus:
        beat = self.heartbeat()
        fresh = self._fresh_beat() is not None
        sup = self.supervisor
        state: WorkerState
        if sup.state == "off" or (sup.state == "stopped" and fresh):
            # a worker elsewhere (another container) still counts
            state = "running" if fresh else "off"
        elif sup.state in ("starting", "running"):
            ours = fresh and beat.get("pid") == sup.pid
            state = "running" if ours else "starting"
        else:
            state = sup.state
        ml = bool(beat.get("ml")) if fresh else ml_installed()
        message: str | None = None
        if state == "crashed":
            message = sup.message
        elif state == "off":
            message = "Der Analyse-Prozess ist ausgeschaltet (VB_WALL_WORKER=off)."
        elif not ml:
            message = "Ohne KI-Paket: nur Bildwerte (Helligkeit, Farbe, Schärfe)."
        elif fresh and beat.get("models_missing"):
            message = "Modelle fehlen – auf dem Server „models fetch“ ausführen."
        return WorkerStatus(state=state, ml=ml, message=message, last_beat_at=beat.get("beat_at"))

    def status(self) -> AnalysisStatus:
        counts = jobs.counts(self.core.db)
        return AnalysisStatus(
            worker=self.worker(), counts=AnalysisCounts(**counts), analyzers=self.analyzers()
        )

    def set_disabled(self, names: Collection[str], *, actor: str) -> set[str]:
        """Store the complete disabled set (unknown names must be rejected first)."""
        disabled = set(names) - ALWAYS_ON
        with self.core.db.tx():
            jobs.save_disabled(self.core.repos.app_settings, disabled, by=actor)
            self.core.repos.audit.log(
                actor, "wall.analyzers", "", {"disabled": sorted(disabled)}, at=now_iso()
            )
        return disabled

    def rerun(self, scope: Literal["failed", "all"]) -> int:
        return jobs.rerun(self.core.db, scope)

    def photo_analysis(self, public_id: str) -> PhotoAnalysis | None:
        photo = self.core.repos.photos.get(public_id)
        if photo is None:
            return None
        row = jobs.get(self.core.db, photo.id)
        data = row.data if row else {}
        return PhotoAnalysis(
            photo_id=photo.public_id,
            state=cast(AnalysisState, row.state) if row else "pending",
            attempts=row.attempts if row else 0,
            error=row.error if row else None,
            finished_at=row.finished_at if row else None,
            versions=row.versions if row else {},
            facts=jobs.facts(self.core.db, photo.id),
            boxes=[AnalysisBox.model_validate(b) for b in data.get("boxes", [])],
            details=[DetailLine.model_validate(d) for d in data.get("details", [])],
        )

    def request(self, public_id: str) -> PhotoAnalysis | None:
        photo = self.core.repos.photos.get(public_id)
        if photo is None:
            return None
        jobs.request(self.core.db, photo.id)
        return self.photo_analysis(public_id)
