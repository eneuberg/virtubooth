"""Path and query parameters shared by the admin routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Path

from ....core import errors
from ....domain.constants import FP_HASH_PATTERN, MAX_ID, PHOTO_ID_PATTERN

PhotoId = Annotated[str, Path(pattern=PHOTO_ID_PATTERN)]
UserId = Annotated[int, Path(ge=1, lt=MAX_ID)]
FpHash = Annotated[str, Path(pattern=FP_HASH_PATTERN)]


def blank(value: str | None) -> str | None:
    value = value.strip() if value is not None else None
    return value or None


def parse_hidden(raw: str | None) -> bool | None:
    """hidden=true|hidden → only hidden, false|visible → only visible, all/'' → both."""
    value = (blank(raw) or "all").lower()
    if value in ("all", "both"):
        return None
    if value in ("1", "true", "yes", "hidden"):
        return True
    if value in ("0", "false", "no", "visible"):
        return False
    raise errors.bad_request("Ungültiger Filter für versteckt/sichtbar.", "invalid_filter")


def parse_bool_filter(raw: str | None) -> bool | None:
    value = (blank(raw) or "all").lower()
    if value in ("all", "both"):
        return None
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    raise errors.bad_request("Ungültiger Filter.", "invalid_filter")
