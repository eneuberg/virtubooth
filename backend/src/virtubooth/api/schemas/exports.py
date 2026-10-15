"""Request and response models of the admin exports (`/api/admin/exports`) and
the Instagram board's additions (`/api/admin/instagram/{handle}/...`)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from ...domain import exports as dx
from ...domain.constants import EXT_ID_PATTERN

# ------------------------------------------------------------------ options

TIMELAPSE_FPS_DEFAULT = 12  # as `python -m virtubooth.tools.timelapse`
TIMELAPSE_FPS_MAX = 30


class ArchiveOptions(BaseModel):
    """A zip of the photos, CSV lists, manifest.json and README.txt."""

    model_config = ConfigDict(extra="forbid")

    include_hidden: bool = Field(
        default=False, description="Also hidden photos (in photos/<activity>/hidden/)."
    )
    include_db: bool = Field(
        default=False,
        description=(
            "Add a consistent copy of the database: guests (IP addresses, fingerprints, bans),"
            " photo rows, device bans, the audit log and the upload settings. Admin sessions"
            " and export jobs are removed and the file is vacuumed."
        ),
    )


class TimelapseOptions(BaseModel):
    """An H.264 .mp4 of one activity's photos in upload order (needs ffmpeg)."""

    model_config = ConfigDict(extra="forbid")

    extension: str = Field(
        default="beer", pattern=EXT_ID_PATTERN, description="Whose photos (activity id)."
    )
    fps: int = Field(
        default=TIMELAPSE_FPS_DEFAULT, ge=1, le=TIMELAPSE_FPS_MAX, description="Photos per second."
    )
    crossfade: bool = Field(default=False, description="Blend smoothly from photo to photo.")
    include_hidden: bool = Field(default=False, description="Also hidden photos.")


ExportOptions = ArchiveOptions | TimelapseOptions
OPTION_MODELS: dict[dx.ExportKind, type[ExportOptions]] = {
    "archive": ArchiveOptions,
    "timelapse": TimelapseOptions,
}

# ------------------------------------------------------------------ request


class ArchiveExportIn(BaseModel):
    kind: Literal["archive"]
    options: ArchiveOptions = Field(default_factory=ArchiveOptions)


class TimelapseExportIn(BaseModel):
    kind: Literal["timelapse"]
    options: TimelapseOptions = Field(default_factory=TimelapseOptions)


class ExportIn(
    RootModel[Annotated[ArchiveExportIn | TimelapseExportIn, Field(discriminator="kind")]]
):
    """Start an export: `kind` plus its `options` (all optional)."""


# ----------------------------------------------------------------- response


class ExportJob(BaseModel):
    id: str
    kind: dx.ExportKind
    status: dx.ExportStatus
    progress: float | None = Field(
        description="0..1 while running, 1 when done, null while queued; a failed job keeps "
        "the last value."
    )
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None = Field(description="Why it failed: German, shown as-is.")
    file_name: str | None = Field(description="Set when done.")
    bytes: int | None = Field(description="File size, set when done.")
    options: ArchiveOptions | TimelapseOptions = Field(
        description="The options it runs with (defaults filled in)."
    )
    download_url: str | None = Field(description="`GET` it for the file; set when done.")

    @classmethod
    def of(cls, job: dx.ExportJob) -> ExportJob:
        done = job.status == "done"
        return cls(
            id=job.id,
            kind=job.kind,
            status=job.status,
            progress=job.progress,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error=job.error,
            file_name=job.file_name if done else None,
            bytes=job.bytes if done else None,
            options=_options(job),
            download_url=f"/api/admin/exports/{job.id}/download" if done else None,
        )


def _options(job: dx.ExportJob) -> ExportOptions:
    model = OPTION_MODELS[job.kind]
    try:
        return model.model_validate(job.options)
    except ValidationError:
        # a record from another version: show the defaults rather than fail the list
        return model()


class ExportCreatedOut(BaseModel):
    """202 with the new job; 200 with the job of this kind that is already
    queued or running (`created` false; its options may differ)."""

    job: ExportJob
    created: bool


class ExportJobsOut(BaseModel):
    jobs: list[ExportJob] = Field(description="Newest first.")
    public_base_url: str | None = Field(
        description="The public address (Allgemeines, else VB_PUBLIC_BASE_URL); null: "
        "automatic from the request."
    )
    ffmpeg: bool = Field(description="ffmpeg is installed: timelapse jobs can run.")


class ExportDeletedOut(BaseModel):
    ok: Literal[True]
    id: str


# ---------------------------------------------------------------- instagram


class InstagramDoneIn(BaseModel):
    done: bool


class InstagramDoneOut(BaseModel):
    handle: str = Field(description="Normalized (lower case, no @).")
    done: bool
    changed: bool
