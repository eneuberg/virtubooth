"""The wall's port to the photo analysis (`extensions/wall/enrich/`, PLAN-WALL §4.5).

The wall talks to the analysis only through `Enrichment`. `load_enrichment()`
builds `enrich.service.EnrichmentService(core)` when that package exists and
falls back to `NullEnrichment` (no analysis: `analysis: "off"`, no categories)
when it does not.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...runtime import Core

log = logging.getLogger("virtubooth.wall")

SERVICE_MODULE = "virtubooth.extensions.wall.enrich.service"
_ENRICH_PACKAGE = "virtubooth.extensions.wall.enrich"

# settings key the analysis admin writes: {disabled: [names], by}; absent = DEFAULT_DISABLED
ANALYZERS_KEY = "x.wall.analyzers"
DEFAULT_DISABLED = ("age",)
# every analyzer name (PLAN-WALL §3/W3); categories ask which of them are enabled
ANALYZERS = ("basic", "faces", "emotion", "gestures", "objects", "tags", "age")
# facts shown on the wall (WallPhoto.facts); the rest stay admin-only
PUBLIC_FACTS = ("people", "faces", "hands", "smiles")


@dataclass(frozen=True)
class PhotoFilter:
    """Which photos may win a category: these sources (None = all) and created
    at or before `not_after` (ISO, like `photos.created_at`). The service adds
    `hidden_at IS NULL AND deleted_at IS NULL` itself."""

    sources: tuple[str, ...] | None
    not_after: str


class PhotoSummary(Protocol):
    @property
    def state(self) -> str: ...
    @property
    def facts(self) -> Mapping[str, float]: ...


class CategoryDef(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def emoji(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def line(self) -> str: ...
    @property
    def needs(self) -> tuple[str, ...]: ...
    def label(self, value: float) -> str: ...
    def available(self, enabled_analyzers: Collection[str]) -> str | None: ...


class CategoryWinners(Protocol):
    @property
    def category(self) -> CategoryDef: ...
    # (internal photo id, value), best first
    @property
    def winners(self) -> Sequence[tuple[int, float]]: ...


class Enrichment(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def summaries(self, photo_ids: Sequence[int]) -> Mapping[int, PhotoSummary]: ...
    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]: ...
    def catalogue(self) -> Sequence[CategoryDef]: ...
    def winners(
        self, ids: Sequence[str], flt: PhotoFilter, per_category: int = 3
    ) -> Sequence[CategoryWinners]: ...


class NullEnrichment:
    """No analysis installed: nothing analysed, no categories."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def summaries(self, photo_ids: Sequence[int]) -> Mapping[int, PhotoSummary]:
        return {}

    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]:
        return rev, []

    def catalogue(self) -> Sequence[CategoryDef]:
        return []

    def winners(
        self, ids: Sequence[str], flt: PhotoFilter, per_category: int = 3
    ) -> Sequence[CategoryWinners]:
        return []


def load_enrichment(core: Core) -> Enrichment:
    """The analysis service, or NullEnrichment when its package is missing."""
    try:
        module = importlib.import_module(SERVICE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in (SERVICE_MODULE, _ENRICH_PACKAGE):
            raise
        log.info("photo analysis not installed: the wall runs without categories")
        return NullEnrichment()
    service: Enrichment = module.EnrichmentService(core)
    return service


def enabled_analyzers(disabled: object) -> list[str]:
    """Analyzer names minus the stored disabled set (`x.wall.analyzers.disabled`)."""
    names = disabled if isinstance(disabled, list) else list(DEFAULT_DISABLED)
    return [a for a in ANALYZERS if a not in names]
