"""The wall's port to the photo analysis (`extensions/wall/enrich/`, PLAN-WALL §4.5).

The wall talks to the analysis only through `Enrichment`; the app uses
`enrich.service.EnrichmentService(core)`, the tests a fake. The value types
(`PhotoFilter`, `PhotoSummary`, `CategoryDef`, `CategoryWinners`) are the
analysis' own.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from .enrich.categories import PhotoFilter
from .enrich.service import EnrichmentService, PhotoSummary

if TYPE_CHECKING:
    from ...runtime import Core

__all__ = ["PUBLIC_FACTS", "Enrichment", "PhotoFilter", "PhotoSummary", "load_enrichment"]

# facts shown on the wall (WallPhoto.facts); the rest stay admin-only
PUBLIC_FACTS = ("people", "faces", "hands", "smiles")


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
    def active_analyzers(self) -> set[str]:
        """Analyzers that are switched on and able to run (categories ask)."""
        ...


def load_enrichment(core: Core) -> Enrichment:
    """The app's analysis service (it owns the worker process)."""
    return EnrichmentService(core)
