"""The analysis admin API (PLAN §4.4, PLAN-NIGHT §4.3). Paths are relative to the
wall extension's router (`/api/x/wall`). Admin session required; mutations
pass the CSRF origin check (middleware) like every admin route.

Analyses are frozen (PLAN-NIGHT N3): there is no route to analyse a photo
a second time."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ....api.deps import AdminDep, CoreDep, require_admin
from ....core import errors
from . import values
from .analyzers import BY_NAME
from .schemas import AnalysisStatus, AnalyzerIn, AnalyzersIn, PhotoAnalysis
from .service import EnrichmentService, InvalidSettings
from .values import ValuesOut

router = APIRouter(
    tags=["wall"],
    dependencies=[Depends(require_admin)],
    responses=errors.error_responses(400, 401, 403, 404, 422, 429),
)


@router.get("/admin/analysis")
def analysis_status(core: CoreDep) -> AnalysisStatus:
    """Worker state, photo counts per state, the queue and the analyzers
    (with description, model size, stats and settings)."""
    return EnrichmentService.of(core).status()


@router.put("/admin/analysis/analyzers")
def set_analyzers(body: AnalyzersIn, core: CoreDep, admin: AdminDep) -> AnalysisStatus:
    """Switch analyzers off: `disabled` is the complete set (an empty list
    switches everything on, FairFace age included). `basic` always runs."""
    for name in body.disabled:
        if name not in BY_NAME:
            raise errors.bad_request(f"Unbekannte Analyse: {name}.", "unknown_analyzer")
    service = EnrichmentService.of(core)
    service.set_disabled(body.disabled, actor=admin.actor)
    return service.status()


@router.put("/admin/analysis/analyzers/{name}")
def set_analyzer(name: str, body: AnalyzerIn, core: CoreDep, admin: AdminDep) -> AnalysisStatus:
    """Switch one analyzer on or off and change its settings. Applies to
    photos analysed from now on; finished analyses never change."""
    if name not in BY_NAME:
        raise errors.bad_request(f"Unbekannte Analyse: {name}.", "unknown_analyzer")
    service = EnrichmentService.of(core)
    try:
        service.set_analyzer(name, enabled=body.enabled, settings=body.settings,
                             actor=admin.actor)  # fmt: skip
    except InvalidSettings as exc:
        raise errors.bad_request(str(exc), "invalid_analyzer_settings") from None
    return service.status()


@router.get("/admin/photos/{public_id}/analysis")
def photo_analysis(public_id: str, core: CoreDep) -> PhotoAnalysis:
    """One photo's analysis: facts, boxes, German details, its object list,
    detection runs, property scores, durations and the guest's opt-outs
    (live). A photo the worker has not reached yet is `pending`."""
    result = EnrichmentService.of(core).photo_analysis(public_id)
    if result is None:
        raise errors.not_found("Foto nicht gefunden.")
    return result


@router.get("/admin/values")
def analysis_values(core: CoreDep) -> ValuesOut:
    """The values categories can use (PLAN-NIGHT §4.2) and the object labels
    seen so far."""
    service = EnrichmentService.of(core)
    return values.catalogue(core.db, service.active_analyzers())
