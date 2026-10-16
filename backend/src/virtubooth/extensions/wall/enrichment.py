"""The wall's port to the photo analysis (`extensions/wall/enrich/`, PLAN-WALL §4.5)
and the wall's categories (PLAN-NIGHT N13).

The wall talks to the analysis worker only through `Enrichment`; the app uses
`enrich.service.EnrichmentService(core)`, the tests a fake. The categories are
rows in `wall_categories` (rule specs, `enrich/engine.py`), evaluated over the
database; `board()` gives the wall and the admin their categories with
winners and the LLM's verdicts.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .enrich import engine, presets
from .enrich.engine import Comment, PhotoFilter, StoredCategory, Winner
from .enrich.service import EnrichmentService, PhotoSummary

if TYPE_CHECKING:
    from ...runtime import Core

__all__ = [
    "PUBLIC_FACTS",
    "BoardEntry",
    "Enrichment",
    "PhotoFilter",
    "PhotoSummary",
    "board",
    "load_enrichment",
]

# facts shown on the wall (WallPhoto.facts); the rest stay admin-only
PUBLIC_FACTS = ("people", "faces", "hands", "smiles")


class Enrichment(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def summaries(self, photo_ids: Sequence[int]) -> Mapping[int, PhotoSummary]: ...
    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]: ...
    def active_analyzers(self) -> set[str]:
        """Analyzers that are switched on and able to run (categories ask)."""
        ...


def load_enrichment(core: Core) -> Enrichment:
    """The app's analysis service (it owns the worker process)."""
    return EnrichmentService(core)


@dataclass(frozen=True)
class BoardEntry:
    category: StoredCategory
    reason: str | None  # why it cannot win (German), None: available
    winners: list[Winner]
    # photo id → the AI's cached comment, for the best `verdict.count` winners
    comments: Mapping[int, Comment]

    def first_comment(self) -> tuple[int, Comment] | None:
        """The best-ranked winner's comment (the deprecated single verdict)."""
        for w in self.winners:
            found = self.comments.get(w.photo_id)
            if found is not None:
                return w.photo_id, found
        return None


def board(
    core: Core, active: Collection[str], flt: PhotoFilter, *, enabled_only: bool,
    ids: Collection[str] | None = None,
) -> list[BoardEntry]:  # fmt: skip
    """The categories (position order; seeded on first use) with their
    winners under `flt` and the AI's comments on them."""
    db = core.db
    presets.ensure_seeded(db, core.repos.app_settings)
    props, external = engine.availability_context(db)
    cached = engine.comments(db)
    out: list[BoardEntry] = []
    for cat in engine.stored(db):
        if (enabled_only and not cat.enabled) or (ids is not None and cat.id not in ids):
            continue
        reason = engine.spec_availability(cat.spec, active, props, external)
        winners = engine.evaluate(core, cat.spec, flt)
        verdict = cat.spec.get("verdict")
        comments: dict[int, Comment] = {}
        if verdict:
            for w in winners[: int(verdict.get("count") or 1)]:
                found = cached.get((cat.id, w.photo_id))
                if found is not None:
                    comments[w.photo_id] = found
        out.append(BoardEntry(cat, reason, winners, comments))
    return out
