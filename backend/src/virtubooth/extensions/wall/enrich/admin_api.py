"""The analysis admin API (PLAN §4.4, PLAN-NIGHT §4.3). Paths are relative to the
wall extension's router (`/api/x/wall`). Admin session required; mutations
pass the CSRF origin check (middleware) like every admin route.

Analyses are frozen (PLAN-NIGHT N3): there is no route to analyse a photo
a second time."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ....api.deps import AdminDep, CoreDep, require_admin
from ....core import errors
from .analyzers import BY_NAME
from .schemas import AnalysisImageIn, AnalysisStatus, AnalyzerIn, AnalyzersIn, PhotoAnalysis
from .service import EnrichmentService, InvalidSettings, MlMissing

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


@router.put("/admin/analysis/image")
def set_analysis_image(body: AnalysisImageIn, core: CoreDep, admin: AdminDep) -> AnalysisStatus:
    """„Erkennung auf“: `original` (the unfiltered original when there is one) or
    `filtered` (the photo as the guest saw it), for every analyzer and the external
    AI's detection. Applies to photos analysed from now on; photos without a
    separate original always use the photo."""
    service = EnrichmentService.of(core)
    service.set_image(body.use, actor=admin.actor)
    return service.status()


@router.post("/admin/analysis/models/download", responses=errors.error_responses(409))
def download_models(core: CoreDep, admin: AdminDep) -> AnalysisStatus:
    """„Modelle herunterladen“: fetch the missing model files (the standard
    ones plus those of enabled analyzers) from the built-in registry, SHA256-
    checked, into the data volume, in the background. The progress is in
    `models.download` of the status. Idempotent: while one runs, or with
    nothing missing, nothing happens. 409 `ml_missing` without the ML packages."""
    service = EnrichmentService.of(core)
    try:
        service.download_models(actor=admin.actor)
    except MlMissing:
        raise errors.ApiError(
            409, "ml_missing",
            "Die KI-Pakete fehlen in diesem Docker-Image, Modelle allein helfen nicht. "
            "Das Image mit VB_ML=1 bauen (in Coolify: Variable VB_ML=1, dann Redeploy).",
        ) from None  # fmt: skip
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
