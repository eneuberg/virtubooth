"""Admin exports: start an archive or timelapse job, list them, download
the file, delete them (see services/exports.py)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Response
from fastapi.responses import FileResponse

from ....core.errors import error_responses, json_error_responses
from ....domain.constants import PHOTO_ID_PATTERN
from ....domain.exports import MEDIA_TYPES
from ...deps import EVENT_CURSOR_HEADER, AdminDep, CoreDep
from ...schemas.exports import (
    ExportCreatedOut,
    ExportDeletedOut,
    ExportIn,
    ExportJob,
    ExportJobsOut,
)
from ._params import ADMIN_ERROR_STATUSES

router = APIRouter(responses=error_responses(409))

# server-generated, the same shape as photo ids
JobId = Annotated[str, Path(pattern=PHOTO_ID_PATTERN)]

_BINARY = {"schema": {"type": "string", "format": "binary"}}
DOWNLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The file as an attachment: archive is a zip, timelapse an mp4.",
        "content": {"application/zip": _BINARY, "video/mp4": _BINARY},
    },
    # errors are JSON, not the file's type (overrides the admin router's entries)
    **json_error_responses(*ADMIN_ERROR_STATUSES, 409),
}


@router.get("/exports")
def list_exports(core: CoreDep) -> ExportJobsOut:
    """Every job, newest first, plus what the export form needs."""
    exports = core.services.exports
    return ExportJobsOut(
        jobs=[ExportJob.of(j) for j in exports.jobs()],
        public_base_url=core.services.host_settings.public_base_url(),
        ffmpeg=exports.ffmpeg_available(),
    )


@router.post(
    "/exports",
    status_code=202,
    responses={200: {"model": ExportCreatedOut, "description": "Already queued or running."}},
)
def create_export(
    body: ExportIn, response: Response, core: CoreDep, admin: AdminDep
) -> ExportCreatedOut:
    """Queue a job (202). One job per kind at a time: while one is queued or
    running, that one comes back (200, `created` false). Follow it through
    `export.updated` events or by polling `GET /api/admin/exports`."""
    request = body.root
    job, created = core.services.exports.create(request.kind, request.options, actor=admin.actor)
    if not created:
        response.status_code = 200
    return ExportCreatedOut(job=ExportJob.of(job), created=created)


@router.get("/exports/{job_id}/download", response_class=FileResponse, responses=DOWNLOAD_RESPONSES)
def download_export(job_id: JobId, response: Response, core: CoreDep) -> FileResponse:
    """The finished file (409 `export_not_ready` while queued, running or failed)."""
    download = core.services.exports.download(job_id)
    return FileResponse(
        download.path,
        media_type=MEDIA_TYPES[download.job.kind],
        filename=download.file_name,
        # a returned response doesn't get the dependency's headers by itself
        headers={EVENT_CURSOR_HEADER: response.headers[EVENT_CURSOR_HEADER]},
    )


@router.delete("/exports/{job_id}")
def delete_export(job_id: JobId, core: CoreDep, admin: AdminDep) -> ExportDeletedOut:
    """Delete a job and its file; a queued job is cancelled. Not while it
    runs (409 `export_running`)."""
    core.services.exports.delete(job_id, actor=admin.actor)
    return ExportDeletedOut(ok=True, id=job_id)
