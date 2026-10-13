"""The analysis admin API (PLAN §4.4). Paths are relative to the wall extension's
router (`/api/x/wall`): WINT includes `router` there. Admin session required;
mutations pass the CSRF origin check (middleware) like every admin route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ....api.deps import AdminDep, CoreDep, require_admin
from ....core import errors
from .analyzers import BY_NAME
from .schemas import AnalysisStatus, AnalyzersIn, PhotoAnalysis, RerunIn, RerunOut
from .service import EnrichmentService

router = APIRouter(
    tags=["wall"],
    dependencies=[Depends(require_admin)],
    responses=errors.error_responses(400, 401, 403, 404, 422, 429),
)


@router.get("/admin/analysis")
def analysis_status(core: CoreDep) -> AnalysisStatus:
    """Worker state, photo counts per state and the analyzers."""
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


@router.post("/admin/analysis/rerun")
def rerun(body: RerunIn, core: CoreDep) -> RerunOut:
    """Analyse failed (or all) photos again; the worker picks them up newest first."""
    return RerunOut(queued=EnrichmentService.of(core).rerun(body.scope))


@router.get("/admin/photos/{public_id}/analysis")
def photo_analysis(public_id: str, core: CoreDep) -> PhotoAnalysis:
    """One photo's analysis: facts, boxes, German details. A photo the worker
    has not reached yet is `pending`."""
    result = EnrichmentService.of(core).photo_analysis(public_id)
    if result is None:
        raise errors.not_found("Foto nicht gefunden.")
    return result


@router.post("/admin/photos/{public_id}/analysis")
def request_analysis(public_id: str, core: CoreDep) -> PhotoAnalysis:
    """„Neu analysieren“: queue this photo again (state `pending`)."""
    result = EnrichmentService.of(core).request(public_id)
    if result is None:
        raise errors.not_found("Foto nicht gefunden.")
    return result
