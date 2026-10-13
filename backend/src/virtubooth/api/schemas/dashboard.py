"""The admin dashboard's live overview (`GET /api/admin/overview`).

Definitions live in domain/overview.py; "now" is the last 5 minutes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OverviewGuests(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int = Field(description="Every guest (device) that joined.")
    active_now: int = Field(
        description="Guests, not banned, whose page was open in the last 5 minutes "
        "(it reports every minute while it is visible)."
    )
    uploading_now: int = Field(description="Distinct guests with an upload in the last 5 minutes.")
    instagram: int = Field(description="Guests that gave an Instagram handle.")
    banned: int
    paused: int = Field(
        description="Guests whose own uploads are paused (by hand or new-guest pause)."
    )


class OverviewScans(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scanned: int = Field(description="Browsers that opened a valid QR link (since `since`).")
    joined: int = Field(description="Of those, the ones that joined (linked to a guest).")
    not_joined: int = Field(description="Scanned but never joined: `scanned - joined`.")
    waiting_now: int = Field(
        description="Not joined, and the page talked to the server in the last 5 minutes."
    )
    since: str | None = Field(
        description="When counting started (the first visitor). Guests from before have no "
        "visitor until their browser comes back."
    )


class OverviewPhotos(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int = Field(description="Photos not deleted.")
    visible: int
    hidden: int
    last_15_min: int = Field(
        description="Uploads received in the last 15 minutes (hidden or deleted ones too)."
    )
    last_60_min: int = Field(description="Uploads received in the last 60 minutes.")
    last_upload_at: str | None


class OverviewActivity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    photos: int = Field(description="Photos not deleted.")
    visible: int
    last_60_min: int


class OverviewOut(BaseModel):
    """Aggregate, first-party counters for the host's dashboard."""

    at: str = Field(description="Server time of this snapshot (ISO-8601 UTC).")
    active_minutes: int = Field(description="The window of „jetzt“ in minutes (5).")
    guests: OverviewGuests
    scans: OverviewScans
    photos: OverviewPhotos
    activities: list[OverviewActivity] = Field(
        description="Every loaded activity that takes photos, plus ids that only old photos have."
    )
