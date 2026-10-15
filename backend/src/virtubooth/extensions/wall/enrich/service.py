"""`EnrichmentService`: what the wall (W1) and the admin API use (PLAN §4.5).

Constructed once per app as `EnrichmentService(core)`; `start()` spawns and
supervises the worker process, `stop()` ends it. Everything else reads the
database the worker writes, so it also works with a worker in another
container (`VB_WALL_WORKER=off` here, heartbeat in `x.wall.worker`).
"""

from __future__ import annotations

import json
import logging
import threading
import weakref
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from ....core.clock import now_iso
from . import jobs, models, objects
from .analyzers import ALWAYS_ON, BY_NAME, INFOS, SETTINGS, ml_installed
from .engine import PhotoFilter
from .schemas import (
    AnalysisBox,
    AnalysisCounts,
    AnalysisQueue,
    AnalysisState,
    AnalysisStatus,
    AnalyzerSettingSpec,
    AnalyzerStats,
    AnalyzerStatus,
    DetailLine,
    DetectionRun,
    ObjectBox,
    OptOutState,
    PhotoAnalysis,
    PhotoObject,
    PropertyScores,
    WorkerState,
    WorkerStatus,
)
from .supervisor import Supervisor

if TYPE_CHECKING:
    from ....runtime import Core

__all__ = ["EnrichmentService", "PhotoFilter", "PhotoSummary"]

log = logging.getLogger("virtubooth.wall.enrich")

# a heartbeat older than this counts as gone (the worker beats every 10 s)
BEAT_FRESH_S = 35.0
_CHUNK = 500


@dataclass(frozen=True)
class PhotoSummary:
    state: str
    facts: Mapping[str, float]


# the app's service per Core (weak: a service nobody holds is just recreated)
_services: weakref.WeakValueDictionary[int, EnrichmentService] = weakref.WeakValueDictionary()
_services_lock = threading.Lock()


def _age_s(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


def _int_or_none(value: Any) -> int | None:
    """A heartbeat number as an int (bools and junk are no numbers)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(value)


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


class InvalidSettings(ValueError):
    """Analyzer settings outside their schema (German message)."""


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
        # the heartbeat's stats outlive the beat's freshness (they are history)
        stats = self.heartbeat().get("stats")
        stats = stats if isinstance(stats, dict) else {}
        settings = jobs.analyzer_settings(self.core.repos.app_settings)
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
            st = stats.get(info.name)
            st = st if isinstance(st, dict) else {}
            out[info.name] = AnalyzerStatus(
                name=info.name, title=info.title, kind=info.kind, version=info.version,
                enabled=info.name not in disabled, available=reason is None, reason=reason,
                facts=list(info.facts), description=info.description,
                size_mb=round(sum(models.BY_NAME[m].size for m in info.models
                                  if m in models.BY_NAME) / 1e6, 1),
                stats=AnalyzerStats(
                    processed=_int_or_none(st.get("processed")) or 0,
                    errors=_int_or_none(st.get("errors")) or 0,
                    avg_ms=_float_or_none(st.get("avg_ms")),
                    last_ms=_float_or_none(st.get("last_ms")),
                ),
                settings=settings.get(info.name),
                settings_schema=[
                    AnalyzerSettingSpec(key=x.key, title=x.title, min=x.min, max=x.max,
                                        step=x.step)
                    for x in SETTINGS.get(info.name, ())
                ],
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
        elif fresh and self._missing_for_enabled(beat):
            message = "Modelle fehlen – auf dem Server „models fetch“ ausführen."
        # the worker's own numbers only while it beats (a stale beat is a dead process)
        live: Mapping[str, Any] = beat if fresh else {}
        errors = live.get("load_errors")
        return WorkerStatus(
            state=state, ml=ml, message=message, last_beat_at=beat.get("beat_at"),
            processed=_int_or_none(live.get("processed")),
            rss_mb=_int_or_none(live.get("rss_mb")),
            load_errors=(
                {str(k): str(v) for k, v in errors.items()} if isinstance(errors, dict) else {}
            ),
        )  # fmt: skip

    def _missing_for_enabled(self, beat: Mapping[str, Any]) -> bool:
        missing = set(beat.get("models_missing") or [])
        disabled = self.disabled()
        return any(m in missing for i in INFOS if i.name not in disabled for m in i.models)

    def status(self) -> AnalysisStatus:
        counts = jobs.counts(self.core.db)
        return AnalysisStatus(
            worker=self.worker(), counts=AnalysisCounts(**counts),
            queue=AnalysisQueue(**jobs.queue(self.core.db)), analyzers=self.analyzers(),
        )  # fmt: skip

    def set_disabled(self, names: Collection[str], *, actor: str) -> set[str]:
        """Store the complete disabled set (unknown names must be rejected first)."""
        disabled = set(names) - ALWAYS_ON
        with self.core.db.tx():
            jobs.save_disabled(self.core.repos.app_settings, disabled, by=actor)
            self.core.repos.audit.log(
                actor, "wall.analyzers", "", {"disabled": sorted(disabled)}, at=now_iso()
            )
        return disabled

    def set_analyzer(
        self, name: str, *, enabled: bool, settings: Mapping[str, float] | None, actor: str
    ) -> None:
        """Switch one analyzer and/or change its settings (they apply to photos
        analysed afterwards; analyses are frozen). Raises InvalidSettings."""
        specs = {x.key: x for x in SETTINGS.get(name, ())}
        if name in ALWAYS_ON and not enabled:
            raise InvalidSettings("Die Bildwerte laufen immer.")
        clean: dict[str, float] = {}
        for key, value in (settings or {}).items():
            spec = specs.get(key)
            if spec is None:
                raise InvalidSettings(f"Unbekannte Einstellung: {key}.")
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InvalidSettings(f"Ungültiger Wert für „{spec.title}“.")
            if not spec.min <= value <= spec.max or (spec.integer and value != int(value)):
                raise InvalidSettings(
                    f"„{spec.title}“ muss zwischen {spec.min:g} und {spec.max:g} liegen."
                )
            clean[key] = int(value) if spec.integer else float(value)
        repo = self.core.repos.app_settings
        with self.core.db.tx():
            disabled = jobs.disabled_analyzers(repo)
            disabled = (disabled - {name}) if enabled else (disabled | {name})
            all_settings = jobs.analyzer_settings(repo)
            if clean:
                all_settings[name] = all_settings.get(name, {}) | clean
            jobs.save_disabled(repo, disabled, by=actor, settings=all_settings)
            self.core.repos.audit.log(
                actor, "wall.analyzers", name,
                {"enabled": enabled, "settings": clean} if clean else {"enabled": enabled},
                at=now_iso(),
            )  # fmt: skip

    def photo_analysis(self, public_id: str) -> PhotoAnalysis | None:
        photo = self.core.repos.photos.get(public_id)
        if photo is None:
            return None
        db = self.core.db
        row = jobs.get(db, photo.id)
        data = row.data if row else {}
        flags = db.one("SELECT analysis_opt_out, ai_opt_out FROM users WHERE id=?",
                       (photo.user_id,))  # fmt: skip
        objs = objects.objects_of(db, [photo.id]).get(photo.id, [])
        props = [
            PropertyScores(
                name=r["name"], archived=r["archived_at"] is not None, scores=_scores(r["scores"])
            )
            for r in db.all(
                "SELECT p.name, p.archived_at, s.scores FROM property_scores s "
                "JOIN llm_properties p ON p.id = s.property_id WHERE s.photo_id=? ORDER BY p.name",
                (photo.id,),
            )
        ]
        durations = data.get("durations_ms")
        return PhotoAnalysis(
            photo_id=photo.public_id,
            state=cast(AnalysisState, row.state) if row else "pending",
            attempts=row.attempts if row else 0,
            error=row.error if row else None,
            finished_at=row.finished_at if row else None,
            versions=row.versions if row else {},
            facts=jobs.facts(db, photo.id),
            boxes=[AnalysisBox.model_validate(b) for b in data.get("boxes", [])],
            details=[DetailLine.model_validate(d) for d in data.get("details", [])],
            objects=[
                PhotoObject(
                    idx=o.idx,
                    label=o.label,
                    label_de=o.label_de,
                    score=o.score,
                    box=ObjectBox(x=o.box[0], y=o.box[1], w=o.box[2], h=o.box[3])
                    if o.box
                    else None,
                    source=o.source,
                    model=o.model,
                )
                for o in objs
            ],
            runs=[DetectionRun.model_validate(r) for r in objects.runs_of(db, photo.id)],
            opt_out=OptOutState(
                analysis=bool(flags and flags[0]), external_ai=bool(flags and flags[1])
            ),
            opt_out_at_analysis=bool(data.get("opt_out", False)),
            properties=props,
            durations_ms={str(k): int(v) for k, v in durations.items()}
            if isinstance(durations, dict)
            else {},
        )


def _scores(raw: str) -> list[float | None]:
    try:
        values = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(values, list):
        return []
    return [
        float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None for v in values
    ]
