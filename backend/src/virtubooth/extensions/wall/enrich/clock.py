"""The party's wall clock for German labels („um 19:42“, „13.10.2026, 19:42“).

$VB_TIMEZONE (blank: Europe/Berlin), the zone the app's exports use: the
container's own clock runs in UTC."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ....core.clock import DEFAULT_TIMEZONE


def party_zone() -> ZoneInfo:
    name = os.environ.get("VB_TIMEZONE", "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local(moment: str | float) -> datetime:
    """An ISO timestamp or Unix seconds on the party's clock."""
    if isinstance(moment, str):
        return datetime.fromisoformat(moment).astimezone(party_zone())
    return datetime.fromtimestamp(moment, party_zone())


def unix(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()
