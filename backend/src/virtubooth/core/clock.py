"""Timestamps. Stored and sent as ISO-8601 UTC with milliseconds
(`2026-10-13T01:39:22.113+00:00`): they compare correctly as strings."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# VB_TIMEZONE's default: the party's wall clock for file names
DEFAULT_TIMEZONE = "Europe/Berlin"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


def local_now(timezone: str) -> datetime:
    """Wall-clock time of the party (file names use it)."""
    return datetime.now(ZoneInfo(timezone))
