"""The dashboard's live overview: counters over guests, scans and photos.

Definitions (also in the OpenAPI descriptions and docs/overhaul/contracts/api.md §7):

- "now" is the last ACTIVE_MINUTES (5) minutes.
- A guest is *seen* on every guest API request (throttled to one write per
  device and minute, see services/presence.py), so "active now" means the page
  was open and talking to the server, not only that a photo came in.
- A *visitor* is one browser that opened a valid QR link (the `vb_vid` cookie).
  Counting starts with the v4 migration: guests from before have no visitor row
  until their browser comes back (then it is linked to them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

ACTIVE_MINUTES: Final = 5
RECENT_SHORT_MINUTES: Final = 15
RECENT_LONG_MINUTES: Final = 60


@dataclass(frozen=True)
class GuestCounts:
    total: int
    active_now: int
    uploading_now: int
    instagram: int
    banned: int
    paused: int


@dataclass(frozen=True)
class ScanCounts:
    scanned: int
    joined: int
    not_joined: int
    waiting_now: int
    since: str | None


@dataclass(frozen=True)
class PhotoCounts:
    total: int
    visible: int
    hidden: int
    last_15_min: int
    last_60_min: int
    last_upload_at: str | None


@dataclass(frozen=True)
class ActivityCounts:
    id: str
    photos: int
    visible: int
    last_60_min: int


@dataclass(frozen=True)
class Overview:
    at: str
    guests: GuestCounts
    scans: ScanCounts
    photos: PhotoCounts
    activities: list[ActivityCounts] = field(default_factory=list)
