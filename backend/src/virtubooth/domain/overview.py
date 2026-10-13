"""The dashboard's live overview: counters over guests, scans and photos.

Definitions (also in the OpenAPI descriptions and docs/overhaul/contracts/api.md §7):

- "now" is the last ACTIVE_MINUTES (5) minutes.
- A guest is *seen* on every guest API request (throttled to one write per
  device and minute, see services/presence.py), so "active now" means the page
  was open and talking to the server, not only that a photo came in.
- The guest page also reports every minute while it is visible (`POST
  /api/here`, the heartbeat), so a guest whose page is open but idle stays
  "active now" too; a hidden page (other app, locked phone) stops reporting.
- *Online time* per guest: the visible time added up from those beats
  (`users.online_seconds`) and the visits (`users.online_sessions`: a beat
  after more than ONLINE_GAP_SECONDS without one starts a new visit, nothing is
  added for the gap). A guest is *online now* when its last beat
  (`users.online_at`, cleared by the beat a page sends when it is hidden) is at
  most ONLINE_GAP_SECONDS old.
- A *visitor* is one browser that opened a valid QR link (the `vb_vid` cookie).
  Counting starts with the v4 migration: guests from before have no visitor row
  until their browser comes back (then it is linked to them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

ACTIVE_MINUTES: Final = 5
RECENT_SHORT_MINUTES: Final = 15
RECENT_LONG_MINUTES: Final = 60
# the page beats every 60 s while visible; 150 s tolerates one lost beat
ONLINE_GAP_SECONDS: Final = 150


def seconds_since(at: str | None, now: datetime) -> float | None:
    """Seconds from the ISO time `at` to `now` (None: no time)."""
    if at is None:
        return None
    return (now - datetime.fromisoformat(at)).total_seconds()


def is_online(online_at: str | None, now: datetime | None = None) -> bool:
    """The guest's page is open and visible: a beat within ONLINE_GAP_SECONDS."""
    elapsed = seconds_since(online_at, now or datetime.now(UTC))
    return elapsed is not None and elapsed <= ONLINE_GAP_SECONDS


@dataclass(frozen=True)
class Beat:
    """What one heartbeat adds to a guest's online time (see `beat()`)."""

    add_seconds: int
    new_visit: bool


def beat(online_at: str | None, now: datetime, *, visible: bool) -> Beat:
    """The online-time accounting of one beat. A beat within the gap of the
    visit's last one adds the time in between (whole seconds); a visible beat
    after a longer gap (or the first one) starts a new visit and adds nothing.
    Afterwards a visible beat keeps the visit open (`online_at` = now), a
    hidden one closes it (`online_at` = NULL)."""
    elapsed = seconds_since(online_at, now)
    if elapsed is not None and elapsed <= ONLINE_GAP_SECONDS:
        return Beat(add_seconds=max(0, int(elapsed)), new_visit=False)
    return Beat(add_seconds=0, new_visit=visible)


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
